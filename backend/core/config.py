from pydantic_settings import BaseSettings, SettingsConfigDict

class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Embedding Config
    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-base"
    EMBEDDING_BATCH_SIZE: int = 32
    E5_QUERY_PREFIX: str = "query: "

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
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


pipeline_settings = PipelineSettings()
api_settings = APISettings()
