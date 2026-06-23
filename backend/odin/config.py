"""Application settings, loaded from environment / .env.

Conventional env var names (case-insensitive) map onto fields. The blob store uses
standard AWS_* credentials read by boto3 directly; only the endpoint/bucket live here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- core ---
    environment: str = "dev"
    debug: bool = False

    # --- database (Postgres + pgvector + Apache AGE) ---
    database_url: str = "postgresql+asyncpg://odin:odin@localhost:25000/odin"
    age_graph: str = "odin"

    # --- blob store (S3-compatible; MinIO in dev). AWS_* creds are read by boto3. ---
    s3_endpoint_url: str | None = None  # e.g. http://localhost:9000 for MinIO
    s3_region: str = "us-east-1"
    s3_bucket: str = "odin"

    # --- LLM (OpenAI-compatible; OpenRouter by default, repointable to OpenAI) ---
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    answer_model: str = "z-ai/glm-5.2"

    # --- embeddings ---
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # --- worker ---
    worker_poll_interval_seconds: float = 1.0
    worker_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
