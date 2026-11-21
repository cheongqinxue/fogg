"""Postgres baseline bootstrap and profile persistence."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import date
from uuid import uuid4

import pytest
from backend.accounts import login_external_account, seed_debug_account
from backend.database import get_pool, init_database, shutdown_database
from backend.migrate import migrate_database
from backend.profiles import (
    BioDetails,
    ImmigrationDetails,
    get_profile,
    save_bio_details,
    save_immigration_status,
)
from psycopg import AsyncConnection, sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import CheckViolation, ForeignKeyViolation


@pytest.fixture
async def isolated_database_url() -> AsyncIterator[str]:
    url = os.environ.get("FOGG_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("FOGG_TEST_POSTGRES_URL not set")
    schema = sql.Identifier(f"fogg_test_{uuid4().hex}")
    async with await AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        try:
            yield make_conninfo(url, options=f"-csearch_path={schema.as_string()}")
        finally:
            await conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


@pytest.mark.integration
async def test_bootstrap_and_profile_persistence(
    isolated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = isolated_database_url
    with pytest.raises(RuntimeError, match="uninitialized"):
        await migrate_database(url, apply=False)
    await asyncio.gather(migrate_database(url), migrate_database(url))
    await migrate_database(url, apply=False)

    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    monkeypatch.setenv("FOGG_ENV", "test")
    await init_database()
    try:
        async with get_pool().connection() as conn:
            versions = await conn.execute("SELECT name FROM fogg_schema_migrations ORDER BY name")
            assert await versions.fetchall() == [{"name": "0001_baseline.sql"}]
            layout = await conn.execute(
                "SELECT account_id FROM agent_user_layout WHERE account_id = 'first'"
            )
            assert await layout.fetchall() == []
        missing = str(uuid4())
        assert await get_profile(missing) is None
        async with get_pool().connection() as conn:
            cursor = await conn.execute("INSERT INTO users DEFAULT VALUES RETURNING account_id")
            account_id = (await cursor.fetchone())["account_id"]
            cursor = await conn.execute("INSERT INTO users DEFAULT VALUES RETURNING account_id")
            second_account_id = (await cursor.fetchone())["account_id"]
        account_key = str(account_id)
        empty = await get_profile(account_key)
        assert empty is not None
        assert empty.account_id == account_id
        assert empty.bio == BioDetails()
        assert empty.immigration_statuses == []
        assert empty.preference_summary is None
        assert empty.trip_summary is None

        bio = BioDetails(
            name="Alex", home_formatted_address="Example address", home_country_code="SG"
        )
        assert await save_bio_details(account_key, bio)
        citizenship = ImmigrationDetails(country_code="SG", kind="citizenship")
        visa = ImmigrationDetails(country_code="JP", kind="visa", valid_until=date(2030, 1, 1))
        status_id = await save_immigration_status(account_key, citizenship)
        assert status_id is not None
        assert await save_immigration_status(account_key, visa) is not None
        assert not await save_bio_details(missing, bio)
        assert (
            await save_immigration_status(str(second_account_id), visa, status_id=status_id) is None
        )

        profile = await get_profile(account_key)
        assert profile is not None
        assert profile.bio == bio
        assert {status.kind for status in profile.immigration_statuses} == {"citizenship", "visa"}
        corrected = citizenship.model_copy(update={"label": "Confirmed by user"})
        assert (
            await save_immigration_status(account_key, corrected, status_id=status_id) == status_id
        )

        invalid = visa.model_copy(update={"valid_from": date(2031, 1, 1)})
        with pytest.raises(CheckViolation):
            await save_immigration_status(account_key, invalid)

        async with get_pool().connection() as conn:
            await conn.execute(
                "INSERT INTO user_summaries (account_id, preference_summary) VALUES (%s, %s)",
                (account_id, "Prefers rail"),
            )
        profile = await get_profile(account_key)
        assert profile is not None
        assert profile.preference_summary == "Prefers rail"
    finally:
        await shutdown_database()


@pytest.mark.integration
async def test_itinerary_snapshot_belongs_to_trip(isolated_database_url: str) -> None:
    await migrate_database(isolated_database_url)
    async with await AsyncConnection.connect(isolated_database_url) as conn:
        cursor = await conn.execute("INSERT INTO users DEFAULT VALUES RETURNING account_id")
        (account_id,) = await cursor.fetchone()
        cursor = await conn.execute(
            "INSERT INTO trips (account_id, name) VALUES (%s, 'Nagano'), (%s, 'Busan') "
            "RETURNING trip_id, status",
            (account_id, account_id),
        )
        (trip_id, status), (other_trip_id, _) = await cursor.fetchall()
        assert status == "draft"
        cursor = await conn.execute(
            "INSERT INTO itinerary_versions (trip_id, version_number) VALUES (%s, 1) "
            "RETURNING itinerary_version_id",
            (trip_id,),
        )
        (version_id,) = await cursor.fetchone()
        await conn.execute(
            "INSERT INTO itinerary_version_steps VALUES (%s, 1, 'home', '{\"name\": \"Home\"}')",
            (version_id,),
        )
        with pytest.raises(ForeignKeyViolation):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE trips SET head_itinerary_version_id = %s WHERE trip_id = %s",
                    (version_id, other_trip_id),
                )
        await conn.execute(
            "UPDATE trips SET head_itinerary_version_id = %s WHERE trip_id = %s",
            (version_id, trip_id),
        )
        await conn.execute("DELETE FROM trips WHERE trip_id = %s", (trip_id,))
        cursor = await conn.execute("SELECT count(*) FROM itinerary_version_steps")
        assert await cursor.fetchone() == (0,)


@pytest.mark.integration
async def test_debug_account_seed(
    isolated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from httpx import ASGITransport, AsyncClient
    from utils.settings import reset_settings_for_tests

    monkeypatch.setenv("AGENT_DATABASE_URL", isolated_database_url)
    monkeypatch.setenv("FOGG_ENV", "test")
    monkeypatch.setenv("IDENTITY_BACKEND", "password")
    from api.app import app

    await init_database()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            credentials = {"email": "user@fogg.com", "password": "password"}
            await seed_debug_account()
            assert (await client.post("/v1/auth/login", json=credentials)).status_code == 401

            monkeypatch.setenv("FOGG_ENV", "dev")
            reset_settings_for_tests()
            await asyncio.gather(seed_debug_account(), seed_debug_account())
            async with get_pool().connection() as conn:
                cursor = await conn.execute("SELECT count(*) AS total FROM users")
                assert (await cursor.fetchone())["total"] == 1
                cursor = await conn.execute("SELECT count(*) AS total FROM user_sessions")
                assert (await cursor.fetchone())["total"] == 0
            response = await client.post("/v1/auth/login", json=credentials)
            assert response.status_code == 200
    finally:
        await shutdown_database()


@pytest.mark.integration
async def test_password_registration_login_and_session_isolation(
    isolated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.app import app
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("AGENT_DATABASE_URL", isolated_database_url)
    monkeypatch.setenv("FOGG_ENV", "test")
    monkeypatch.setenv("IDENTITY_BACKEND", "password")
    registration = {
        "email": "Alex@Example.test",
        "password": "a local test passphrase",
        "name": "  Alex  ",
        "home_formatted_address": "Example address",
        "home_country_code": "sg",
        "immigration_statuses": [
            {"country_code": "sg", "kind": "citizenship"},
            {"country_code": "jp", "kind": "permanent_resident"},
        ],
    }
    await init_database()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/v1/auth/session")).status_code == 401
            invalid = await client.post(
                "/v1/auth/register", json={**registration, "password": "short"}
            )
            assert invalid.status_code == 422
            assert "short" not in invalid.text

            response = await client.post("/v1/auth/register", json=registration)
            assert response.status_code == 201, response.text
            assert response.headers["Cache-Control"] == "no-store"
            session = response.json()
            account_id = session["account_id"]
            token = session["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            assert (await client.get("/v1/auth/session", headers=headers)).json() == {
                "account_id": account_id
            }
            assert (
                await client.get(f"/v1/users/{account_id}/messages", headers=headers)
            ).status_code == 200
            assert (
                await client.get("/v1/users/someone-else/messages", headers=headers)
            ).status_code == 403

            duplicate = await client.post("/v1/auth/register", json=registration)
            assert duplicate.status_code == 409
            async with get_pool().connection() as conn:
                users = await conn.execute(
                    "SELECT count(*) AS n FROM users WHERE legacy_subject IS NULL"
                )
                assert (await users.fetchone())["n"] == 1
                secrets = await conn.execute(
                    "SELECT email, password_hash FROM user_password_credentials"
                )
                stored = await secrets.fetchone()
                assert stored["email"] == "alex@example.test"
                assert stored["password_hash"] != registration["password"].encode()
                session_rows = await conn.execute("SELECT token_hash FROM user_sessions")
                assert (await session_rows.fetchone())["token_hash"] != token.encode()

            profile = await get_profile(account_id)
            assert profile is not None
            assert profile.bio.name == "Alex"
            assert profile.bio.gender is None
            assert profile.bio.home_country_code == "SG"
            assert {(entry.country_code, entry.kind) for entry in profile.immigration_statuses} == {
                ("SG", "citizenship"),
                ("JP", "permanent_resident"),
            }

            login = {"email": "alex@example.test", "password": registration["password"]}
            wrong = await client.post("/v1/auth/login", json={**login, "password": "incorrect"})
            assert wrong.status_code == 401
            second = await client.post("/v1/auth/login", json=login)
            assert second.status_code == 200
            assert second.json()["account_id"] == account_id
            assert second.json()["access_token"] != token
            assert (await client.delete("/v1/auth/session", headers=headers)).status_code == 204
            assert (await client.get("/v1/auth/session", headers=headers)).status_code == 401

            # Expiration invalidates a session even if the logout endpoint was never called.
            async with get_pool().connection() as conn:
                await conn.execute(
                    "UPDATE user_sessions SET expires_at = now() - interval '1 second'"
                )
            expired = {"Authorization": f"Bearer {second.json()['access_token']}"}
            assert (await client.get("/v1/auth/session", headers=expired)).status_code == 401

            issuer = "https://issuer.example"
            same_identity = await asyncio.gather(
                login_external_account(issuer, "shared-subject"),
                login_external_account(issuer, "shared-subject"),
            )
            assert same_identity[0].account_id == same_identity[1].account_id
            assert same_identity[0].access_token != same_identity[1].access_token
            assert same_identity[0].account_id != account_id
            other_identity = await login_external_account(
                "https://other-issuer.example", "shared-subject"
            )
            assert other_identity.account_id != same_identity[0].account_id
    finally:
        await shutdown_database()


@pytest.mark.integration
async def test_google_exchange_issues_and_revokes_normal_session(
    isolated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.app import app
    from httpx import ASGITransport, AsyncClient
    from utils import identity

    monkeypatch.setenv("AGENT_DATABASE_URL", isolated_database_url)
    monkeypatch.setenv("FOGG_ENV", "prod")
    monkeypatch.setenv("IDENTITY_BACKEND", "google")
    monkeypatch.setenv("IDENTITY_PROJECT_ID", "fogg-test-project")
    verification_calls: list[tuple[str, str]] = []

    def verify(token: str, project_id: str) -> str | None:
        verification_calls.append((token, project_id))
        return "verified-subject" if token == "provider-id-token" else None

    monkeypatch.setattr(identity, "_verify_google_identity_token", verify)
    await migrate_database(isolated_database_url)
    await init_database()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            provider_headers = {"Authorization": "Bearer provider-id-token"}
            assert (
                await client.get("/v1/auth/session", headers=provider_headers)
            ).status_code == 401
            assert not verification_calls

            response = await client.post("/v1/auth/google", json={"id_token": "provider-id-token"})
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            session = response.json()
            assert session["access_token"] != "provider-id-token"
            assert verification_calls == [("provider-id-token", "fogg-test-project")]

            session_headers = {"Authorization": f"Bearer {session['access_token']}"}
            verified = await client.get("/v1/auth/session", headers=session_headers)
            assert verified.json() == {"account_id": session["account_id"]}
            response = await client.get(
                f"/v1/users/{session['account_id']}/messages", headers=session_headers
            )
            assert response.status_code == 200
            assert len(verification_calls) == 1

            assert (
                await client.delete("/v1/auth/session", headers=session_headers)
            ).status_code == 204
            assert (
                await client.get("/v1/auth/session", headers=session_headers)
            ).status_code == 401
            invalid = await client.post("/v1/auth/google", json={"id_token": "invalid"})
            assert invalid.status_code == 401
    finally:
        await shutdown_database()
