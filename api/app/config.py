"""Runtime settings, loaded from environment / .env (see .env.example for the contract)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Qdrant
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "professors"
    qdrant_timeout: int = 30

    # Embedding
    embedding_provider: str = "dashscope"  # dashscope | openai
    embedding_api_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    )
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # LLM (keyword expansion)
    llm_provider: str = "dashscope"  # dashscope | openai | none
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"
    openai_llm_model: str = "gpt-4o-mini"

    # Service
    demo_mode: bool = False
    admin_token: str = ""
    professors_data_path: str = ""  # JSONL of the sample professors; auto-resolved if blank

    @property
    def effective_embedding_key(self) -> str:
        # Mirror production: EMBEDDING_API_KEY falls back to QWEN_API_KEY (same DashScope account).
        return self.embedding_api_key or self.qwen_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
