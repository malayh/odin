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
    database_url: str = "postgresql+psycopg://odin:odin@localhost:25000/odin"
    age_graph: str = "odin"

    # --- blob store (S3-compatible; MinIO in dev). AWS_* creds are read by boto3. ---
    s3_endpoint_url: str | None = None  # e.g. http://localhost:9000 for MinIO
    s3_region: str = "us-east-1"
    s3_bucket: str = "odin"

    # --- LLM (OpenAI-compatible; OpenRouter by default, repointable to OpenAI) ---
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    answer_model: str = "z-ai/glm-5.2"
    tier2_model: str = "deepseek/deepseek-v4-pro"

    # --- embeddings ---
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # --- chunking ---
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 64
    chunk_min_tokens: int = 64

    # --- graph expansion (retrieval) ---
    expand_entities_per_doc: int = 16
    expand_neighbors_per_entity: int = 16

    # --- ask (rerank + answer) ---
    ask_top_k: int = 20
    ask_context_chunks: int = 8
    answer_context_max_chars: int = 8000

    # --- worker ---
    worker_max_attempts: int = 5

    # --- consolidation (deep_consolidate: dossier + skeptic-veto + confidence vote) ---
    consolidation_cosine_gate: float = 0.7
    consolidation_ann_top_k: int = 10
    consolidation_neutral_judges: int = 2
    consolidation_neutral_quorum: int = 2
    consolidation_confidence_floor: float = 0.6
    consolidation_skeptic_floor: float = 0.7
    consolidation_judge_concurrency: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
