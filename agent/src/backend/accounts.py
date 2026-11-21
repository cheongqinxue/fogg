"""Local email authentication and transactional account registration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import scrypt, sha256
from secrets import compare_digest, token_bytes, token_urlsafe
from uuid import UUID

from psycopg import AsyncConnection

from backend.database import get_pool
from backend.profiles import BioDetails, ImmigrationDetails

_SESSION_LIFETIME = timedelta(hours=12)
_DUMMY_SALT = token_bytes(16)
_DUMMY_HASH = token_bytes(32)
_password_slots = asyncio.Semaphore(2)


class EmailAlreadyRegistered(ValueError):
    """The email address already belongs to an account."""


@dataclass(frozen=True)
class Session:
    account_id: str
    access_token: str
    expires_at: datetime


def _derive_password(password: str, salt: bytes) -> bytes:
    return scrypt(
        password.encode("utf-8"), salt=salt, n=2**16, r=8, p=2, dklen=32, maxmem=80 * 1024**2
    )


async def _hash_password(password: str, salt: bytes) -> bytes:
    async with _password_slots:
        return await asyncio.to_thread(_derive_password, password, salt)


def _token_hash(token: str) -> bytes:
    return sha256(token.encode("utf-8")).digest()


async def _issue_session(conn: AsyncConnection, account_id: UUID) -> Session:
    session = Session(str(account_id), token_urlsafe(32), datetime.now(UTC) + _SESSION_LIFETIME)
    await conn.execute(
        "DELETE FROM user_sessions WHERE account_id = %s AND expires_at <= now()",
        (account_id,),
    )
    await conn.execute(
        "INSERT INTO user_sessions (token_hash, account_id, expires_at) VALUES (%s, %s, %s)",
        (_token_hash(session.access_token), account_id, session.expires_at),
    )
    return session


async def register_account(
    email: str, password: str, bio: BioDetails, immigration_statuses: list[ImmigrationDetails]
) -> Session:
    """Create the account, its profile, and its first session in one transaction."""
    salt = token_bytes(16)
    password_hash = await _hash_password(password, salt)
    async with get_pool().connection() as conn:
        cursor = await conn.execute("INSERT INTO users DEFAULT VALUES RETURNING account_id")
        account_id = (await cursor.fetchone())["account_id"]
        cursor = await conn.execute(
            """
            INSERT INTO user_password_credentials (account_id, email, password_salt, password_hash)
            VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO NOTHING
            """,
            (account_id, email, salt, password_hash),
        )
        if cursor.rowcount == 0:
            raise EmailAlreadyRegistered

        await conn.execute(
            """
            INSERT INTO user_bio_details
                (account_id, name, gender, home_formatted_address, home_country_code)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (account_id, bio.name, bio.gender, bio.home_formatted_address, bio.home_country_code),
        )
        if immigration_statuses:
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO immigration_statuses (account_id, country_code, kind)
                    VALUES (%s, %s, %s)
                    """,
                    [
                        (account_id, entry.country_code, entry.kind)
                        for entry in immigration_statuses
                    ],
                )
        return await _issue_session(conn, account_id)


async def login_account(email: str, password: str) -> Session | None:
    """Check a password and issue a session for the matching account."""
    async with get_pool().connection() as conn:
        cursor = await conn.execute(
            """
            SELECT account_id, password_salt, password_hash
            FROM user_password_credentials
            WHERE email = %s
            """,
            (email,),
        )
        row = await cursor.fetchone()
    # Derive a hash even when an account does not exist.
    actual = await _hash_password(password, row["password_salt"] if row else _DUMMY_SALT)
    matches = compare_digest(actual, row["password_hash"] if row else _DUMMY_HASH)
    if not matches or row is None:
        return None
    async with get_pool().connection() as conn:
        return await _issue_session(conn, row["account_id"])


async def get_session_account_id(token: str) -> str | None:
    """Resolve a valid session token to the account ID."""
    async with get_pool().connection() as conn:
        cursor = await conn.execute(
            """
            SELECT account_id FROM user_sessions WHERE token_hash = %s AND expires_at > now()
            """,
            (_token_hash(token),),
        )
        row = await cursor.fetchone()
        return str(row["account_id"]) if row else None


async def revoke_session(token: str) -> None:
    """Delete the session for this token if it exists."""
    async with get_pool().connection() as conn:
        await conn.execute("DELETE FROM user_sessions WHERE token_hash = %s", (_token_hash(token),))


async def login_external_account(issuer: str, subject: str) -> Session:
    """Issue a FOGG session for a verified provider identity."""
    async with get_pool().connection() as conn:
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"fogg-identity:{issuer}:{subject}",),
        )
        cursor = await conn.execute(
            "SELECT account_id FROM account_identities WHERE provider = %s AND subject = %s",
            (issuer, subject),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await conn.execute("INSERT INTO users DEFAULT VALUES RETURNING account_id")
            row = await cursor.fetchone()
            await conn.execute(
                "INSERT INTO account_identities (provider, subject, account_id) VALUES (%s, %s, %s)",
                (issuer, subject, row["account_id"]),
            )
        return await _issue_session(conn, row["account_id"])
