from backend.core.config import llm_settings
from backend.pipeline.stages.extract.llm.adapters.gemini import extraction_model
from backend.pipeline.stages.extract.output_schema import ExtractionOutput
from backend.pipeline.stages.extract.prompt_builder import build_prompt


def extract_sentiment(article_text: str) -> tuple[ExtractionOutput, str]:
    prompt = build_prompt(article_text)
    result = extraction_model.invoke(prompt)
    return result, llm_settings.GEMINI_MODEL_NAME
