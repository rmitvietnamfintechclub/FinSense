import logging
from dataclasses import dataclass

import httpx
from google.api_core.exceptions import (
    DeadlineExceeded,
    ResourceExhausted,
    ServiceUnavailable,
)
from google.genai.errors import APIError
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from backend.core.schemas.sentiment import AIResponse, ConceptSentiment, TickerSentiment
from backend.pipeline.stages.extract.client import invoke_llm
from backend.pipeline.stages.extract.prompt_builder import build_prompt

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Outcome of one attempt.

    ai_response is None only on failure. A success that found nothing returns
    an AIResponse with empty lists — callers must treat these differently:
    retry the first, mark the second done.
    """

    ai_response: AIResponse | None = None
    failure_type: str | None = None
    dropped_count: int = 0

    @property
    def succeeded(self) -> bool:
        return self.failure_type is None


def _failed(failure_type: str, message: str, *, code: int | None = None) -> ExtractionResult:
    logger.error(
        "Extraction failed: type=%s code=%s message=%s",
        failure_type,
        code,
        message,
        extra={"failure_type": failure_type, "code": code, "failure_message": message},
    )
    return ExtractionResult(failure_type=failure_type)


def _keep_valid(
    raw: object, item_model: type[BaseModel], label: str
) -> tuple[list[BaseModel], int]:
    """Validate entries one at a time. Bad entries are logged and skipped so a
    single out-of-vocabulary term does not cost the whole article."""
    if not isinstance(raw, list):
        logger.warning("Expected a list for %s_sentiments, got %s", label, type(raw).__name__)
        return [], 0

    kept, dropped = [], 0
    for item in raw:
        try:
            kept.append(item_model.model_validate(item))
        except ValidationError as exc:
            dropped += 1
            logger.warning(
                "Dropped %s entry: %s (%s)", label, item, exc.errors()[0].get("type")
            )
    return kept, dropped


def extract_from_text(article_text: str) -> ExtractionResult:
    try:
        prompt, prompt_version = build_prompt(article_text)
        payload, model_version = invoke_llm(prompt)
    except ResourceExhausted as exc:
        return _failed("llm_quota_exhausted", str(exc), code=429)
    except (DeadlineExceeded, ServiceUnavailable) as exc:
        return _failed("llm_unavailable", str(exc))
    except httpx.TimeoutException as exc:
        return _failed("llm_timeout", str(exc))
    except APIError as exc:
        return _failed("llm_api_error", str(exc), code=getattr(exc, "code", None))
    except OutputParserException as exc:
        return _failed("malformed_response", str(exc))
    except FileNotFoundError as exc:
        return _failed("missing_prompt_template", str(exc))
    except RuntimeError as exc:
        return _failed("missing_config", str(exc))
    except Exception as exc:  # noqa: BLE001 — deliberate backstop
        # Last arm of the chain above: every anticipated failure already has its own
        # handler. This one exists so an unanticipated error degrades to a structured
        # ExtractionResult instead of killing the whole run — the type name is kept in
        # the reason so the gap is still diagnosable from the record.
        return _failed(f"unexpected_error[{type(exc).__name__}]", str(exc))

    if not isinstance(payload, dict):
        return _failed("malformed_response", f"expected dict, got {type(payload).__name__}")

    tickers, dropped_t = _keep_valid(payload.get("ticker_sentiments"), TickerSentiment, "ticker")
    concepts, dropped_c = _keep_valid(payload.get("concept_sentiments"), ConceptSentiment, "concept")

    try:
        response = AIResponse(
            ticker_sentiments=tickers,
            concept_sentiments=concepts,
            ai_confidence=payload["ai_confidence"],
            model_version=model_version,
            prompt_version=prompt_version,
        )
    except (KeyError, ValidationError) as exc:
        return _failed("invalid_confidence", str(exc))

    if dropped_t or dropped_c:
        logger.info("Dropped %d ticker, %d concept entries", dropped_t, dropped_c)

    return ExtractionResult(ai_response=response, dropped_count=dropped_t + dropped_c)