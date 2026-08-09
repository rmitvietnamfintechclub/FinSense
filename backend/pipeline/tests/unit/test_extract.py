"""Unit tests for the extract stage.

No network calls: the LLM boundary (`invoke_llm`) is monkeypatched everywhere.
Covers the request schema, prompt rendering, and drop-and-keep behaviour.
"""

import logging

import httpx
import pytest
from google.genai.errors import APIError
from langchain_core.exceptions import OutputParserException

from backend.core.enums import Concept, Ticker
from backend.core.schemas.sentiment import AIResponse
from backend.pipeline.stages.extract import client, extractor, prompt_builder
from backend.pipeline.stages.extract.client import EXTRACTION_SCHEMA
from backend.pipeline.stages.extract.extractor import extract_from_text
from backend.pipeline.stages.extract.prompt_builder import build_prompt

_VALID_TICKER = next(iter(Ticker)).value
_VALID_CONCEPT = next(iter(Concept)).value


def _payload(**overrides) -> dict:
    """A well-formed LLM response, overridable per test."""
    base = {
        "ticker_sentiments": [{"ticker": _VALID_TICKER, "score": -0.5}],
        "concept_sentiments": [{"concept": _VALID_CONCEPT, "score": 0.2}],
        "ai_confidence": 0.8,
    }
    base.update(overrides)
    return base


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace invoke_llm with a canned payload or an exception."""

    def _set(payload=None, *, raises: Exception | None = None, model="test-model"):
        def _fake(prompt: str):
            if raises is not None:
                raise raises
            return payload, model

        monkeypatch.setattr(extractor, "invoke_llm", _fake)

    return _set


# ---------------------------------------------------------------- schema ---


def test_schema_carries_full_ticker_enum():
    """Layer 1 constraint: every VN30 ticker must reach Gemini."""
    values = EXTRACTION_SCHEMA["properties"]["ticker_sentiments"]["items"]["properties"]["ticker"]["enum"]
    assert values == [t.value for t in Ticker]


def test_schema_carries_full_concept_enum():
    values = EXTRACTION_SCHEMA["properties"]["concept_sentiments"]["items"]["properties"]["concept"]["enum"]
    assert values == [c.value for c in Concept]


def test_schema_keys_match_stored_model():
    """The hand-built schema must not drift from AIResponse.

    model_version and prompt_version are stamped by the pipeline, so they are
    deliberately absent from what the LLM is asked to produce.
    """
    stamped = {"model_version", "prompt_version"}
    assert set(EXTRACTION_SCHEMA["properties"]) == set(AIResponse.model_fields) - stamped


def test_schema_omits_stamped_fields():
    """If these leak into the schema, Gemini will invent values for them."""
    assert "model_version" not in EXTRACTION_SCHEMA["properties"]
    assert "prompt_version" not in EXTRACTION_SCHEMA["properties"]


def test_confidence_range_is_zero_to_one():
    confidence = EXTRACTION_SCHEMA["properties"]["ai_confidence"]
    assert confidence["minimum"] == 0.0
    assert confidence["maximum"] == 1.0


def test_all_fields_required():
    assert set(EXTRACTION_SCHEMA["required"]) == set(EXTRACTION_SCHEMA["properties"])


# ---------------------------------------------------------------- prompt ---


def test_prompt_template_resolves_and_renders():
    """Guards the prompts directory path, which is easy to break on a move."""
    prompt, version = build_prompt("NOI DUNG BAI BAO")
    assert "NOI DUNG BAI BAO" in prompt
    assert "{article_text}" not in prompt
    assert version


def test_prompt_survives_literal_json_braces():
    """Few-shot templates will contain JSON. .format() would raise here."""
    prompt, _ = build_prompt('{"ticker": "ACB"}')
    assert '{"ticker": "ACB"}' in prompt


def test_prompt_version_comes_from_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt_builder, "_PROMPTS_DIR", tmp_path)
    (tmp_path / "vtest.txt").write_text("BODY: {article_text}", encoding="utf-8")
    monkeypatch.setattr(prompt_builder.pipeline_settings, "PROMPT_VERSION", "vtest", raising=False)
    prompt_builder._load_template.cache_clear()

    prompt, version = build_prompt("abc")
    assert prompt == "BODY: abc"
    assert version == "vtest"

    prompt_builder._load_template.cache_clear()


def test_missing_template_is_a_handled_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(prompt_builder, "_PROMPTS_DIR", tmp_path / "nope")
    monkeypatch.setattr(prompt_builder.pipeline_settings, "PROMPT_VERSION", "vmissing", raising=False)
    prompt_builder._load_template.cache_clear()

    result = extract_from_text("article")
    assert result.failure_type == "missing_prompt_template"
    assert result.ai_response is None

    prompt_builder._load_template.cache_clear()


# ------------------------------------------------------------ happy path ---


def test_valid_payload_is_stamped_with_versions(fake_llm):
    fake_llm(_payload(), model="gemini-test")
    result = extract_from_text("article")

    assert result.succeeded
    assert result.ai_response.model_version == "gemini-test"
    assert result.ai_response.prompt_version
    assert result.ai_response.ai_confidence == 0.8
    assert result.dropped_count == 0


def test_scores_and_enums_are_parsed(fake_llm):
    fake_llm(_payload())
    entry = extract_from_text("article").ai_response.ticker_sentiments[0]

    assert entry.ticker == Ticker(_VALID_TICKER)
    assert entry.score == -0.5


def test_empty_lists_are_success_not_failure(fake_llm):
    """An article with no covered ticker is processed, not failed.

    stage.py must distinguish this from a None response or it will retry
    articles that were handled correctly.
    """
    fake_llm(_payload(ticker_sentiments=[], concept_sentiments=[]))
    result = extract_from_text("article")

    assert result.succeeded
    assert result.ai_response.ticker_sentiments == []
    assert result.ai_response.concept_sentiments == []


# --------------------------------------------------------- drop and keep ---


def test_unmapped_ticker_dropped_valid_one_kept(fake_llm):
    """The core requirement: one bad term must not cost the whole article."""
    fake_llm(_payload(ticker_sentiments=[
        {"ticker": "NOTREAL", "score": 0.5},
        {"ticker": _VALID_TICKER, "score": -0.5},
    ]))
    result = extract_from_text("article")

    assert result.succeeded
    assert [t.ticker.value for t in result.ai_response.ticker_sentiments] == [_VALID_TICKER]
    assert result.dropped_count == 1


def test_unmapped_concept_dropped(fake_llm):
    fake_llm(_payload(concept_sentiments=[
        {"concept": "E_COMMERCE", "score": 0.4},
        {"concept": _VALID_CONCEPT, "score": 0.1},
    ]))
    result = extract_from_text("article")

    assert [c.concept.value for c in result.ai_response.concept_sentiments] == [_VALID_CONCEPT]
    assert result.dropped_count == 1


@pytest.mark.parametrize("bad_score", [1.5, -1.5])
def test_out_of_range_score_dropped(fake_llm, bad_score):
    fake_llm(_payload(ticker_sentiments=[
        {"ticker": _VALID_TICKER, "score": bad_score},
        {"ticker": _VALID_TICKER, "score": 0.3},
    ]))
    result = extract_from_text("article")

    assert len(result.ai_response.ticker_sentiments) == 1
    assert result.dropped_count == 1


def test_malformed_entries_dropped(fake_llm):
    """Missing key, wrong shape, and a non-dict entry all get skipped."""
    fake_llm(_payload(ticker_sentiments=[
        {"ticker": _VALID_TICKER},
        {"score": 0.5},
        "not a dict",
        {"ticker": _VALID_TICKER, "score": 0.5},
    ]))
    result = extract_from_text("article")

    assert len(result.ai_response.ticker_sentiments) == 1
    assert result.dropped_count == 3


def test_dropped_entries_are_logged(fake_llm, caplog):
    """Drop rate is an Evolution 1 baseline input, so it must be visible."""
    fake_llm(_payload(ticker_sentiments=[{"ticker": "NOTREAL", "score": 0.5}]))
    with caplog.at_level(logging.WARNING):
        extract_from_text("article")

    assert any("NOTREAL" in r.getMessage() for r in caplog.records)


def test_non_list_sentiments_yields_empty(fake_llm):
    fake_llm(_payload(ticker_sentiments={"ticker": _VALID_TICKER}))
    result = extract_from_text("article")

    assert result.succeeded
    assert result.ai_response.ticker_sentiments == []


# ------------------------------------------------ confidence is not partial ---


def test_missing_confidence_fails_article(fake_llm):
    payload = _payload()
    del payload["ai_confidence"]
    fake_llm(payload)

    result = extract_from_text("article")
    assert result.failure_type == "invalid_confidence"
    assert result.ai_response is None


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_out_of_range_confidence_fails_article(fake_llm, bad):
    fake_llm(_payload(ai_confidence=bad))
    assert extract_from_text("article").failure_type == "invalid_confidence"


# ------------------------------------------------------ failure taxonomy ---


@pytest.mark.parametrize("exc, expected", [
    (httpx.TimeoutException("timed out"), "llm_timeout"),
    (OutputParserException("bad json"), "malformed_response"),
    (RuntimeError("LLM_API_KEY is missing"), "missing_config"),
])
def test_failure_types_are_distinguished(fake_llm, exc, expected):
    """Retry logic depends on these labels: a timeout is retryable,
    a missing key is not."""
    fake_llm(raises=exc)
    result = extract_from_text("article")

    assert result.failure_type == expected
    assert result.ai_response is None
    assert not result.succeeded


def test_api_error_is_labelled(fake_llm):
    fake_llm(raises=APIError(429, {"message": "rate limited"}))
    assert extract_from_text("article").failure_type == "llm_api_error"


def test_unexpected_error_names_the_type(fake_llm):
    fake_llm(raises=ZeroDivisionError("boom"))
    assert extract_from_text("article").failure_type == "unexpected_error[ZeroDivisionError]"


def test_non_dict_payload_is_a_failure(fake_llm):
    fake_llm("just a string")
    assert extract_from_text("article").failure_type == "malformed_response"


# --------------------------------------------------------- client wiring ---


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr(client.pipeline_settings, "LLM_API_KEY", "", raising=False)
    client._get_model.cache_clear()

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        client._get_model()

    client._get_model.cache_clear()


def test_model_built_once(monkeypatch):
    """lru_cache must hold: rebuilding per article is slow, and it would let
    the recorded model_version drift from the model that actually ran."""
    calls = []

    class _Fake:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def with_structured_output(self, schema):
            return self

    monkeypatch.setattr(client.pipeline_settings, "LLM_API_KEY", "key", raising=False)
    monkeypatch.setattr(client, "ChatGoogleGenerativeAI", _Fake)
    client._get_model.cache_clear()

    first, name_a = client._get_model()
    second, name_b = client._get_model()

    assert first is second
    assert name_a == name_b
    assert len(calls) == 1

    client._get_model.cache_clear()


