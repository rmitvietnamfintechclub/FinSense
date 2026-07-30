import logging
from datetime import datetime, timezone

import httpx
from google.genai.errors import APIError
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from backend.core.enums import Concept, Ticker
from backend.pipeline.stages.extract.output_schema import ExtractionOutput
from backend.pipeline.stages.extract.unmapped_handler import log_unmapped_concept

logger = logging.getLogger(__name__)

_VALID_TICKERS = {member.value for member in Ticker}
_VALID_CONCEPTS = {member.value for member in Concept}


def _log_failure(failure_type: str, message: str, *, code: int | None = None) -> None:
    # No article/cluster identifier is threaded into run_extract() yet
    # should wire one through here if per-article failure tracing is needed later.
    logger.error(
        "Extraction failed: type=%s code=%s message=%s",
        failure_type,
        code,
        message,
        extra={
            "failure_type": failure_type,
            "code": code,
            "failure_message": message,
            "article_id": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def run_extract(article_text: str) -> tuple[ExtractionOutput | None, str | None]:
    # client.py imports gemini.py, which uses LLMSettings()
    # ValidationError when client.py is first imported, not when it's called.
    # The import is deferred into this try block so that failure is caught
    # here instead of crashing whatever module imports response_parser.
    try:
        from backend.pipeline.stages.extract.llm.client import extract_sentiment
    except ValidationError as exc:
        _log_failure("missing_config", str(exc))
        return None, None

    try:
        result, model_version = extract_sentiment(article_text)
    except ValidationError as exc:
        _log_failure("missing_config", str(exc))
        return None, None
    except httpx.TimeoutException as exc:
        _log_failure("gemini_timeout", str(exc))
        return None, None
    except APIError as exc:
        _log_failure("gemini_api_error", str(exc), code=getattr(exc, "code", None))
        return None, None
    except OutputParserException as exc:
        _log_failure("malformed_response", str(exc))
        return None, None
    except Exception as exc:
        _log_failure(f"unexpected_error[{type(exc).__name__}]", str(exc))
        return None, None

    valid_ticker_sentiments = [
        item for item in result.ticker_sentiments if item.ticker in _VALID_TICKERS
    ]

    valid_concept_sentiments = []
    for item in result.concept_sentiments:
        if item.concept in _VALID_CONCEPTS:
            valid_concept_sentiments.append(item)
        else:
            log_unmapped_concept(item.concept)

    filtered_result = result.model_copy(
        update={
            "ticker_sentiments": valid_ticker_sentiments,
            "concept_sentiments": valid_concept_sentiments,
        }
    )
    return filtered_result, model_version
