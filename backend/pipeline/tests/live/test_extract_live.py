"""Live Gemini integration test — costs real API quota.

Unit tests mock the LLM boundary and prove our own logic. This file proves the
one thing they cannot: that Gemini accepts EXTRACTION_SCHEMA and returns a
payload our parser understands.

Run explicitly:
    pytest backend/pipeline/tests/integration/test_extract_live.py -m live -v -s

Skipped by default so CI needs no API key. Assertions are structural, never on
specific scores — the model is non-deterministic and exact-value asserts flake.
"""

import os

import pytest

from backend.core.enums import Concept, Ticker
from backend.pipeline.stages.extract.extractor import extract_from_text

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("LLM_API_KEY"),
        reason="LLM_API_KEY not set — live test skipped",
    ),
]

# A clearly negative article naming one VN30 ticker. Replace with a real CafeF
# body once you have one; keep the tone unambiguous so the direction assertion
# stays meaningful.
NEGATIVE_ARTICLE = """
Ngân hàng ACB công bố kết quả kinh doanh quý 2 với lợi nhuận trước thuế giảm
mạnh 35% so với cùng kỳ năm trước. Nợ xấu tăng lên mức cao nhất trong ba năm,
buộc ngân hàng phải tăng trích lập dự phòng. Giới phân tích tỏ ra lo ngại về
chất lượng tài sản của ngân hàng trong nửa cuối năm.
"""

IRRELEVANT_ARTICLE = """
Lễ hội ẩm thực đường phố tại Đà Nẵng thu hút hàng nghìn du khách trong dịp cuối
tuần. Ban tổ chức cho biết năm nay có hơn 100 gian hàng tham gia, giới thiệu các
món ăn truyền thống của ba miền.
"""


@pytest.fixture(scope="module")
def negative_result():
    """One API call shared by several assertions — keeps quota use minimal."""
    return extract_from_text(NEGATIVE_ARTICLE)


# ------------------------------------------------- the contract with Gemini ---


def test_schema_is_accepted(negative_result):
    """The main event.

    A 400 here means Gemini rejected EXTRACTION_SCHEMA — most likely the
    `minimum`/`maximum` keywords, which are not guaranteed to be supported.
    Fix: drop them from the schema and state the range in `description`
    instead. Our own bounds checking in the parser is unaffected.
    """
    assert negative_result.failure_type is None, (
        f"Gemini call failed: {negative_result.failure_type}. "
        "Check the schema keywords and the API key."
    )
    assert negative_result.ai_response is not None


def test_payload_keys_match_parser_expectations(negative_result):
    """If Gemini returned different key names, the parser silently produces
    empty lists rather than raising. This catches that."""
    response = negative_result.ai_response
    assert response.ticker_sentiments, (
        "No ticker sentiments parsed. Either the article named no VN30 ticker, "
        "or Gemini used different key names than the schema requested."
    )


def test_nothing_was_dropped(negative_result):
    """Drops here mean the enum constraint is not holding at generation time —
    Gemini is emitting values outside the vocabulary we sent it."""
    assert negative_result.dropped_count == 0, (
        f"{negative_result.dropped_count} entries dropped. "
        "The schema enum may not be reaching the model."
    )


# ---------------------------------------------------------- output validity ---


def test_all_values_are_in_vocabulary(negative_result):
    response = negative_result.ai_response
    for entry in response.ticker_sentiments:
        assert isinstance(entry.ticker, Ticker)
    for entry in response.concept_sentiments:
        assert isinstance(entry.concept, Concept)


def test_scores_are_in_range(negative_result):
    response = negative_result.ai_response
    for entry in response.ticker_sentiments + response.concept_sentiments:
        assert -1.0 <= entry.score <= 1.0


def test_confidence_is_in_range(negative_result):
    assert 0.0 <= negative_result.ai_response.ai_confidence <= 1.0


def test_versions_are_stamped(negative_result):
    response = negative_result.ai_response
    assert response.model_version
    assert response.prompt_version


# ------------------------------------------------------ prompt sanity check ---


def test_negative_article_scores_negative(negative_result):
    """Weak signal, deliberately: only checks direction, not magnitude.

    A failure here does not mean the plumbing is broken — it means the prompt
    is not steering the model. That is a v2 problem, not a client.py problem.
    """
    tickers = negative_result.ai_response.ticker_sentiments
    assert any(entry.score < 0 for entry in tickers), (
        f"Expected a negative score for a clearly negative article, got "
        f"{[(e.ticker.value, e.score) for e in tickers]}"
    )


def test_irrelevant_article_returns_empty_lists():
    """Guards against the model inventing tickers to fill the schema.

    Costs a second API call. Delete if quota is tight — but this is the
    failure mode that would quietly poison every aggregate score.
    """
    result = extract_from_text(IRRELEVANT_ARTICLE)

    assert result.failure_type is None
    assert result.ai_response.ticker_sentiments == [], (
        f"Model fabricated tickers for an unrelated article: "
        f"{[e.ticker.value for e in result.ai_response.ticker_sentiments]}"
    )


# ------------------------------------------------------------------ inspect ---


def test_print_raw_output(negative_result):
    """Not an assertion — run with -s to eyeball the actual output.

    Useful when tuning the prompt: shows exactly what the model produced.
    """
    if negative_result.ai_response:
        print("\n" + negative_result.ai_response.model_dump_json(indent=2))