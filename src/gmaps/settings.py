"""Configuration for the in-process Google Maps client."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from gmaps.quota.store import UsageStore

StoreBackend = Literal["sqlite", "redis"]


class GmapsSettings(BaseSettings):
    """Google Maps client and quota settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_maps_api_key: str = Field(default="", validation_alias="GOOGLE_MAPS_API_KEY")
    fogg_env: Literal["dev", "prod", "test"] = Field(default="dev", validation_alias="FOGG_ENV")

    gmaps_quota_tracking: bool | None = Field(default=None, validation_alias="GMAPS_QUOTA_TRACKING")
    gmaps_quota_store: StoreBackend = Field(default="redis", validation_alias="GMAPS_QUOTA_STORE")
    gmaps_quota_sqlite_path: str = Field(
        default=".data/gmaps-proxy/gmaps_usage.sqlite3",
        validation_alias="GMAPS_QUOTA_SQLITE_PATH",
    )
    gmaps_redis_url: str = Field(default="redis://127.0.0.1:6379/0", validation_alias="GMAPS_REDIS_URL")
    gmaps_quota_log: bool = Field(default=False, validation_alias="GMAPS_QUOTA_LOG")
    gmaps_quota_enforce: bool | None = Field(default=None, validation_alias="GMAPS_QUOTA_ENFORCE")
    gmaps_quota_warn_ratio: float = Field(default=0.8, ge=0.0, le=1.0, validation_alias="GMAPS_QUOTA_WARN_RATIO")
    gmaps_quota_warn_remaining: int = Field(
        default=500,
        ge=0,
        validation_alias="GMAPS_QUOTA_WARN_REMAINING",
    )
    gmaps_cache_enabled: bool = Field(default=True, validation_alias="GMAPS_CACHE_ENABLED")
    gmaps_cache_ttl_seconds: int = Field(default=3600, ge=1, validation_alias="GMAPS_CACHE_TTL_SECONDS")

    # gmaps.requests.base — HTTP retry loop on GoogleMapRequest.call()
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

    def quota_tracking_enabled(self) -> bool:
        """Whether to persist usage for wrapped client calls."""
        if self.gmaps_quota_tracking is not None:
            return self.gmaps_quota_tracking
        return self.fogg_env == "dev"

    def quota_enforce_enabled(self) -> bool:
        """Whether to block calls that would exceed local free-tier caps."""
        if self.gmaps_quota_enforce is not None:
            return self.gmaps_quota_enforce
        return self.quota_tracking_enabled()

    @property
    def effective_quota_tracking(self) -> bool:
        """Resolved quota tracking flag."""
        return self.quota_tracking_enabled()

    @property
    def effective_quota_enforce(self) -> bool:
        """Resolved quota enforcement flag."""
        return self.quota_enforce_enabled()


@lru_cache
def get_settings() -> GmapsSettings:
    """Cached settings."""
    return GmapsSettings()


_store: UsageStore | None = None


def get_usage_store() -> UsageStore:
    """Singleton usage store from settings (Redis by default)."""
    global _store
    if _store is not None:
        return _store
    settings = get_settings()
    if settings.gmaps_quota_store == "sqlite":
        from gmaps.quota.store import SqliteUsageStore

        _store = SqliteUsageStore(settings.gmaps_quota_sqlite_path)
    else:
        from gmaps.quota.store import RedisUsageStore

        _store = RedisUsageStore()
    return _store


def reset_usage_store_for_tests() -> None:
    """Clear cached usage store and settings (pytest)."""
    global _store
    _store = None
    get_settings.cache_clear()
