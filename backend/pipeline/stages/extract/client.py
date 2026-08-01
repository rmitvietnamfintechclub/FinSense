from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

from backend.core.config import pipeline_settings
from backend.core.enums import Concept, Ticker

TICKER_LIST = [t.value for t in Ticker]
CONCEPT_LIST = [c.value for c in Concept]

_SENTIMENT_SCORE = {"type": "number", "minimum": -1.0, "maximum": 1.0}
_AI_SCORE = {"type": "number", "minimum": 0.0, "maximum": 1.0}

def _sentiment_array(key: str, enum_values: list[str], desc: str) -> dict:
    return {
        "type": "array",
        "description": desc,
        "items": {
            "type": "object",
            "properties": {
                key: {"type": "string", "enum": enum_values},
                "score": {**_SENTIMENT_SCORE, "description": "News-coverage tone, -1.0 to 1.0."},
            },
            "required": [key, "score"],
        },
    }


EXTRACTION_SCHEMA = {
    "title": "ExtractionOutput",
    "type": "object",
    "properties": {
        "ticker_sentiments": _sentiment_array(
            "ticker",
            TICKER_LIST,
            "One entry per listed ticker discussed. Empty list if none apply.",
        ),
        "concept_sentiments": _sentiment_array(
            "concept",
            CONCEPT_LIST,
            "One entry per listed concept discussed. Empty list if none apply.",
        ),
        "ai_confidence": {
            **_AI_SCORE,
            "description": "Confidence in the overall correctness of this extraction.",
        },
    },
    "required": ["ticker_sentiments", "concept_sentiments", "ai_confidence"],
}

@lru_cache(maxsize=1)
def _get_model() -> tuple[object, str]:
    if not pipeline_settings.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is missing")
    model_name = pipeline_settings.LLM_MODEL_NAME
    model = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=pipeline_settings.LLM_API_KEY,
        temperature=pipeline_settings.EXTRACTION_TEMPERATURE,
    )
    return model.with_structured_output(EXTRACTION_SCHEMA), model_name


def invoke_llm(prompt: str) -> tuple[dict, str]:
    model, model_name = _get_model()
    return model.invoke(prompt), model_name
