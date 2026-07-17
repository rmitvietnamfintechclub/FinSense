from pydantic_settings import BaseSettings, SettingsConfigDict

class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    EMBEDDING_MODEL_NAME: str = "intfloat/multilingual-e5-base"
    EMBEDDING_BATCH_SIZE: int = 32
    E5_QUERY_PREFIX: str = "query: "


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


pipeline_settings = PipelineSettings()
api_settings = APISettings()