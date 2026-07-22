from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Optional at import time — validated when a connection is actually opened,
    # so modules that merely import config.py don't require a configured DB.
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "FinSense"
    
class PipelineSettings(BaseSettings):
    # Embedding Config
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-base"
    EMBEDDING_BATCH_SIZE: int = 32
    E5_QUERY_PREFIX: str = "query: "
    CLUSTER_SIMILARITY_THRESHOLD: float = 0.91
    # Unlike CLUSTER_SIMILARITY_THRESHOLD, this window is not benchmark-calibrated —
    # it's a placeholder for how long an event keeps accepting new articles.
    CLUSTER_LOOKBACK_DAYS: int = 3

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

class APISettings(BaseSettings):
    pass


database_settings = DatabaseSettings()
pipeline_settings = PipelineSettings()
api_settings = APISettings()
