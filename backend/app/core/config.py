from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NazishAI File Platform"
    env: str = "development"
    api_v1_prefix: str = "/api/v1"

    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str = "us-east-1"
    s3_bucket_chunks: str = "nazishai-chunks"
    s3_bucket_files: str = "nazishai-files"

    qdrant_url: str
    qdrant_collection: str = "nazishai_documents"

    chunk_size_default: int = 100 * 1024 * 1024
    chunk_size_max: int = 512 * 1024 * 1024
    max_file_size: int = 1024**4

    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
