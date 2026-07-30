from langchain_google_genai import ChatGoogleGenerativeAI

from backend.core.config import EXTRACTION_TEMPERATURE, llm_settings
from backend.pipeline.stages.extract.output_schema import ExtractionOutput

_model = ChatGoogleGenerativeAI(
    model=llm_settings.GEMINI_MODEL_NAME,
    google_api_key=llm_settings.GEMINI_API_KEY,
    temperature=EXTRACTION_TEMPERATURE,
)

extraction_model = _model.with_structured_output(ExtractionOutput)
