"""Read-only source DB check: migrate a temporary backup and measure local FAQ matching."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
import statistics
import tempfile
import time
from contextlib import closing
from pathlib import Path

import database as db
import extensions as ext
from backup_db import backup
from reply_policy import match_faq


async def check_database(source):
    source = Path(source).resolve(strict=True)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    old_path = db.DB_PATH
    with tempfile.TemporaryDirectory(prefix="autoreply-release-") as directory:
        snapshot = Path(directory) / "snapshot.db"
        backup(source, snapshot)
        def counts():
            with closing(sqlite3.connect(snapshot)) as conn:
                return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("users", "faq")}
        before = counts()
        try:
            db.DB_PATH = str(snapshot)
            await db.init_db()
            await ext.init_schema()
            after = counts()
            with closing(sqlite3.connect(snapshot)) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if before != after or integrity != "ok":
                raise RuntimeError("Temporary migration did not preserve data or integrity")
        finally:
            db.DB_PATH = old_path
    unchanged = original_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    if not unchanged:
        raise RuntimeError("Source file changed during the check; a running writer may be active")
    return {"integrity": integrity, "row_counts_preserved": before == after, "source_file_unchanged": unchanged}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", help="Existing DB; only a temporary SQLite backup is migrated")
    args = parser.parse_args()
    report = {}
    if args.database:
        report["database_copy"] = await check_database(args.database)
    faqs = [{"question": f"information about product {index}", "answer": "Saved reply", "answer_payload": "{}"} for index in range(1000)]
    durations = []
    for _ in range(10):
        started = time.perf_counter()
        match_faq("How long does shipping take?", faqs, 0.78)
        durations.append((time.perf_counter() - started) * 1000)
    report["matching_microbenchmark"] = {"faq_count": len(faqs), "samples": len(durations), "median_ms": round(statistics.median(durations), 2), "max_ms": round(max(durations), 2), "scope": "local CPU only; excludes SQLite, Telegram and AI network latency"}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
