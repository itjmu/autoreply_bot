"""SQLite-consistent backup / verified restore. No bot or API access."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone


def backup(source, target=None):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("Source database does not exist")
    target = (
        Path(target).resolve()
        if target
        else source.parent
        / "backups"
        / (
            "autoreply-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            + ".sqlite3"
        )
    )
    if target.exists() or target == source:
        raise ValueError("Backup target already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
    return target


def restore(source, target):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if target.exists():
        raise ValueError(
            "Restore requires a new destination; stop the bot and preserve the old DB first"
        )
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source integrity check failed")
    return backup(source, target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("source")
    parser.add_argument("target", nargs="?")
    args = parser.parse_args()
    if args.action == "restore" and not args.target:
        parser.error("restore requires a new target path")
    print(
        backup(args.source, args.target)
        if args.action == "backup"
        else restore(args.source, args.target)
    )
