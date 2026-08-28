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

    # Price Data Settings (FS30: VNDirect finfo API selected as primary provider)
    PRICE_API_URL: str = "https://api-finfo.vndirect.com.vn/v4/stock_prices"
    PRICE_API_TIMEOUT: int = 10  # seconds, per request
    PRICE_QUOTE_MULTIPLIER: float = 1000.0  # provider quotes in thousands of VND

    # LLM Settings
    LLM_API_KEY: str = ""
    LLM_MODEL_NAME: str = "gemini-3.6-flash"
    LLM_TIMEOUT: int = 60          # seconds, per request
    LLM_MAX_RETRIES: int = 1 

    # Extraction Settings
    EXTRACTION_TEMPERATURE: float = 0.0
    PROMPT_VERSION: str = "v1"
    AI_CONFIDENCE_THRESHOLD: float = 0.5

class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DECAY_LAMBDA: dict[str, float] = {"24h": 0.05, "48h": 0.025, "72h": 0.015} 
    WINDOW_HOURS: dict[str, int] = {"24h": 24, "48h": 48, "72h": 72}
    DEFAULT_WINDOW: str = "24h"

    # Dashboard
    DEFAULT_EVENTS_LIMIT: int = 5
    DEFAULT_TICKERS_LIMIT: int = 5
    MAX_PAGE_SIZE: int = 50
    SENTIMENT_BUCKET_THRESHOLD: float = 0.2

    # Ticker detail page (FS-37)
    TICKER_EVENTS_PAGE_SIZE: int = 5
    TICKER_HISTORY_DAYS: list[int] = [7, 30, 90]
    DEFAULT_TICKER_HISTORY_DAYS: int = 30

    # CORS — the two Next.js apps. Browsers block cross-origin fetches without
    # this, so an unlisted frontend origin fails at preflight, not in the route.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]


database_settings = DatabaseSettings()
pipeline_settings = PipelineSettings()
api_settings = APISettings()