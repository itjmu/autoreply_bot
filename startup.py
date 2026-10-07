"""Conservative startup: single local poller and backup before first migration."""

import asyncio
import hashlib
import os
import socket
import sqlite3
from contextlib import closing
from pathlib import Path

import database as db
from extensions import SCHEMA_VERSION
from backup_db import backup


def acquire_instance(token):
    # Same token chooses the same local port without storing or logging the token.
    port = (
        20000
        + int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % 40000
    )
    guard = socket.socket()
    try:
        guard.bind(("127.0.0.1", port))
    except OSError:
        guard.close()
        raise RuntimeError(
            "Another local bot instance may be running, or the guard port is occupied"
        ) from None
    return guard


async def prepare_database():
    path = Path(db.DB_PATH)
    if not path.exists():
        if os.getenv("REQUIRE_EXISTING_DB", "false").lower() == "true":
            raise RuntimeError(
                "DB_PATH is missing. Refusing to create an empty production database."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        return

    def needs_backup():
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        ) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_versions'"
            ).fetchone()
            return (
                not exists
                or not conn.execute(
                    "SELECT 1 FROM schema_versions WHERE version=?", (SCHEMA_VERSION,)
                ).fetchone()
            )

    if await asyncio.to_thread(needs_backup):
        await asyncio.to_thread(backup, path)
