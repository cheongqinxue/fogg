"""Validated application configuration loaded from environment and repo dotenv files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class AppSettings(BaseSettings):
    """Central settings for the API, agent, and functionality modules."""

    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT / "agent" / ".env"), str(_REPO_ROOT / ".env")),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Application environment
    fogg_env: Literal["dev", "prod", "test"] = Field(default="dev", validation_alias="FOGG_ENV")
    cors_origins_raw: str = Field(default="*", validation_alias="CORS_ORIGINS")
    agent_dev_reset_enabled: bool = Field(default=False, validation_alias="AGENT_DEV_RESET_ENABLED")

    # Identity Platform
    identity_backend: Literal["local", "google"] = Field(
        default="local", validation_alias="IDENTITY_BACKEND"
    )
    identity_project_id: str = Field(default="", validation_alias="IDENTITY_PROJECT_ID")

    # Secret encryption
    kms_backend: Literal["local", "google"] = Field(default="local", validation_alias="KMS_BACKEND")
    kms_local_encryption_key: str = Field(default="", validation_alias="KMS_LOCAL_ENCRYPTION_KEY")
    kms_key_name: str = Field(default="", validation_alias="KMS_KEY_NAME")

    # Shared database and Redis connections
    agent_database_url: str | None = Field(default=None, validation_alias="AGENT_DATABASE_URL")
    database_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")
    postgres_user: str = Field(default="fogg", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="fogg", validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="fogg", validation_alias="POSTGRES_DB")
    agent_database_host: str = Field(default="127.0.0.1", validation_alias="AGENT_DATABASE_HOST")
    compose_port_postgres: int = Field(
        default=15432, ge=1, le=65535, validation_alias="COMPOSE_PORT_POSTGRES"
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", validation_alias="REDIS_URL")

    # Google Maps
    google_maps_api_key: str = Field(default="", validation_alias="GOOGLE_MAPS_API_KEY")
    gmaps_quota_tracking: bool | None = Field(default=None, validation_alias="GMAPS_QUOTA_TRACKING")
    gmaps_quota_store: Literal["sqlite", "redis"] = Field(
        default="redis", validation_alias="GMAPS_QUOTA_STORE"
    )
    gmaps_quota_sqlite_path: str = Field(
        default=".data/gmaps-proxy/gmaps_usage.sqlite3",
        validation_alias="GMAPS_QUOTA_SQLITE_PATH",
    )
    gmaps_quota_log: bool = Field(default=False, validation_alias="GMAPS_QUOTA_LOG")
    gmaps_quota_enforce: bool | None = Field(default=None, validation_alias="GMAPS_QUOTA_ENFORCE")
    gmaps_quota_warn_ratio: float = Field(
        default=0.8, ge=0.0, le=1.0, validation_alias="GMAPS_QUOTA_WARN_RATIO"
    )
    gmaps_quota_warn_remaining: int = Field(
        default=500, ge=0, validation_alias="GMAPS_QUOTA_WARN_REMAINING"
    )
    gmaps_cache_enabled: bool = Field(default=True, validation_alias="GMAPS_CACHE_ENABLED")
    gmaps_cache_ttl_seconds: int = Field(
        default=3600, ge=1, validation_alias="GMAPS_CACHE_TTL_SECONDS"
    )
    gmaps_requests_base_max_retries: int = Field(
        default=5,
        ge=0,
        le=50,
        validation_alias="GMAPS_REQUESTS_BASE_MAX_RETRIES",
    )
    gmaps_requests_base_retry_wait_initial_seconds: float = Field(
        default=1.0,
        ge=0.0,
        validation_alias="GMAPS_REQUESTS_BASE_RETRY_WAIT_INITIAL_SECONDS",
    )
    gmaps_requests_base_retry_wait_max_seconds: float = Field(
        default=60.0,
        ge=0.1,
        validation_alias="GMAPS_REQUESTS_BASE_RETRY_WAIT_MAX_SECONDS",
    )

    # Chat model and context trimming
    agent_model: str = Field(default="lfm3:1.7b", validation_alias="AGENT_MODEL")
    openai_base_url: str = Field(
        default="http://127.0.0.1:11434/v1", validation_alias="OPENAI_BASE_URL"
    )
    openai_api_key: str = Field(default="ollama", validation_alias="OPENAI_API_KEY")
    agent_api_base_url: str = Field(
        default="http://127.0.0.1:18080", validation_alias="AGENT_API_BASE_URL"
    )
    agent_max_input_tokens: int = Field(
        default=20_000, ge=1, validation_alias="AGENT_MAX_INPUT_TOKENS"
    )
    agent_limited_tool_max_concurrency: int = Field(
        default=1, ge=1, validation_alias="AGENT_LIMITED_TOOL_MAX_CONCURRENCY"
    )
    agent_tool_judge_max_attempts: int = Field(
        default=3, ge=1, le=5, validation_alias="AGENT_TOOL_JUDGE_MAX_ATTEMPTS"
    )

    # Tracing and tool I/O records
    fogg_tracing_enabled: bool = Field(default=False, validation_alias="FOGG_TRACING_ENABLED")
    fogg_tracing_endpoint: str = Field(
        default="http://127.0.0.1:16006/v1/traces",
        validation_alias="FOGG_TRACING_ENDPOINT",
    )
    fogg_tracing_project: str = Field(default="fogg-dev", validation_alias="FOGG_TRACING_PROJECT")
    agent_tool_io_log_path: str = Field(
        default=".data/tool-io.jsonl", validation_alias="AGENT_TOOL_IO_LOG_PATH"
    )

    # Web search providers and cache
    web_search_provider_order: str = Field(
        default="tavily,exa,firecrawl", validation_alias="WEB_SEARCH_PROVIDER_ORDER"
    )
    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY")
    exa_api_key: str = Field(default="", validation_alias="EXA_API_KEY")
    firecrawl_api_key: str = Field(default="", validation_alias="FIRECRAWL_API_KEY")
    web_search_cache_enabled: bool = Field(
        default=True, validation_alias="WEB_SEARCH_CACHE_ENABLED"
    )
    web_search_cache_ttl_seconds: int = Field(
        default=3600, ge=1, validation_alias="WEB_SEARCH_CACHE_TTL_SECONDS"
    )

    @property
    def cors_origins(self) -> list[str]:
        """Parse the comma-separated CORS allowlist, preserving wildcard behavior."""
        if self.cors_origins_raw.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def web_search_providers(self) -> list[str]:
        """Return configured web providers in preferred fallback order."""
        return [
            name.strip().lower()
            for name in self.web_search_provider_order.split(",")
            if name.strip()
        ]

    @property
    def database_url(self) -> str:
        """Resolve the shared Postgres URL, preferring explicit application URLs."""
        if self.agent_database_url:
            return self.agent_database_url
        if self.database_url_override:
            return self.database_url_override
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql://{user}:{password}@{self.agent_database_host}:"
            f"{self.compose_port_postgres}/{self.postgres_db}"
        )

    def quota_tracking_enabled(self) -> bool:
        """Whether to persist usage for wrapped Google Maps calls."""
        if self.gmaps_quota_tracking is not None:
            return self.gmaps_quota_tracking
        return self.fogg_env == "dev"

    def quota_enforce_enabled(self) -> bool:
        """Whether to block Google Maps calls that would exceed local free-tier caps."""
        if self.gmaps_quota_enforce is not None:
            return self.gmaps_quota_enforce
        return self.quota_tracking_enabled()

    @property
    def effective_quota_tracking(self) -> bool:
        return self.quota_tracking_enabled()

    @property
    def effective_quota_enforce(self) -> bool:
        return self.quota_enforce_enabled()


@lru_cache
def get_settings() -> AppSettings:
    """Return the shared, validated settings object."""
    return AppSettings()


def reset_settings_for_tests() -> None:
    """Clear the cached settings object after tests change environment values."""
    get_settings.cache_clear()
