from __future__ import annotations

import pytest

from utils.settings import AppSettings


def test_settings_parse_environment_and_share_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOGG_ENV", "test")
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "true")
    monkeypatch.setenv("GMAPS_QUOTA_WARN_RATIO", "0.65")
    monkeypatch.setenv("AGENT_DATABASE_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_USER", "fogg user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss/word")
    monkeypatch.setenv("POSTGRES_DB", "fogg")

    settings = AppSettings(_env_file=None)

    assert settings.fogg_env == "test"
    assert settings.gmaps_quota_tracking is True
    assert settings.gmaps_quota_warn_ratio == 0.65
    assert settings.database_url == ("postgresql://fogg+user:p%40ss%2Fword@db.internal:15432/fogg")


def test_explicit_agent_database_url_has_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://agent-db/fogg")
    monkeypatch.setenv("DATABASE_URL", "postgresql://generic-db/fogg")

    assert AppSettings(_env_file=None).database_url == "postgresql://agent-db/fogg"


def test_empty_template_values_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAPS_QUOTA_TRACKING", "")
    monkeypatch.setenv("KMS_LOCAL_ENCRYPTION_KEY", "")

    settings = AppSettings(_env_file=None)

    assert settings.gmaps_quota_tracking is None
    assert settings.kms_local_encryption_key == ""


def test_unknown_gmaps_store_fails_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAPS_QUOTA_STORE", "memcached")

    with pytest.raises(ValueError):
        AppSettings(_env_file=None)
