"""Apply versioned FOGG schema migrations with `python -m backend.migrate`."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from importlib.resources import files

from psycopg import AsyncConnection
from utils.settings import get_settings

_MIGRATION_LOCK = 0x464F47475343484D


async def migrate_database(database_url: str, *, apply: bool = True) -> None:
    """Apply pending migrations or verify that the database has the expected schema version."""
    scripts = sorted(
        (
            item
            for item in files("backend").joinpath("migrations").iterdir()
            if item.name.endswith(".sql")
        ),
        key=lambda item: item.name,
    )
    expected = {script.name: script.read_bytes() for script in scripts}
    if not expected:
        raise RuntimeError("No FOGG schema migrations were packaged.")

    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        if apply:
            # Session lock covers the ledger and all migration transactions.
            # Closing the connection also releases it after a failure.
            await conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK,))
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS fogg_schema_migrations (
                    name TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """)
        else:
            cursor = await conn.execute("SELECT to_regclass('fogg_schema_migrations')")
            if (await cursor.fetchone())[0] is None:
                raise RuntimeError("FOGG schema is uninitialized. Run python -m backend.migrate.")

        cursor = await conn.execute("SELECT name, checksum FROM fogg_schema_migrations")
        applied = dict(await cursor.fetchall())
        checksums = {name: sha256(sql).hexdigest() for name, sql in expected.items()}
        if any(checksums.get(name) != checksum for name, checksum in applied.items()):
            raise RuntimeError(
                "Applied FOGG migrations differ from the packaged migration history."
            )
        if sorted(applied) != list(expected)[: len(applied)]:
            raise RuntimeError("FOGG schema migration history is out of order.")

        for name, sql in expected.items():
            if name in applied:
                continue
            if not apply:
                raise RuntimeError(f"Pending migration {name}. Run python -m backend.migrate.")
            async with conn.transaction():
                # Execute the complete SQL migration without server-side preparation.
                await conn.execute(sql.decode("utf-8"), prepare=False)
                await conn.execute(
                    "INSERT INTO fogg_schema_migrations (name, checksum) VALUES (%s, %s)",
                    (name, checksums[name]),
                )


if __name__ == "__main__":
    asyncio.run(migrate_database(get_settings().database_url))
