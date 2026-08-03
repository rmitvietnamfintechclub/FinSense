from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "FinSense"


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Embedding Config
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-base"
    EMBEDDING_BATCH_SIZE: int = 32
    E5_QUERY_PREFIX: str = "query: "
    CLUSTER_SIMILARITY_THRESHOLD: float = 0.91
    CLUSTER_LOOKBACK_DAYS: int = 3

    # Event Aggregation Config
    # Sources scoring below this AI confidence are excluded from the
    # confidence-weighted event score (numerator and denominator both).
    AI_CONFIDENCE_THRESHOLD: float = 0.4

    # RSS Discovery Config
    RSS_FEEDS: list[tuple[str, str]] = [
        ("CafeF", "https://cafef.vn/thi-truong-chung-khoan.rss"),
        ("VnExpress", "https://vnexpress.net/rss/kinh-doanh.rss"),
    ]

    # HTTP Settings
    HTTP_TIMEOUT: int = 10  # seconds, per request
    HTTP_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }

    # LLM Settings
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "gemini-2.5-flash"
    LLM_TIMEOUT: int = 60          # seconds, per request
    LLM_MAX_RETRIES: int = 1 
    EXTRACTION_TEMPERATURE: float = 0.0
    PROMPT_VERSION: str = "v1"

class APISettings(BaseSettings):
    pass


database_settings = DatabaseSettings()
pipeline_settings = PipelineSettings()
api_settings = APISettings()
