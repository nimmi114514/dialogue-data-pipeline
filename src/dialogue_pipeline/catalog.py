from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from .storage import create_schema


PROFILES = {"default": Path("configs/default.json"), "oasst1": Path("configs/oasst1.json")}
MAX_SOURCE_BYTES = 20 * 1024 * 1024


def create_catalog_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS raw_sources (
            source_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            filename TEXT NOT NULL,
            origin TEXT NOT NULL CHECK (origin IN ('upload', 'local', 'public')),
            profile TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            content BLOB NOT NULL,
            byte_count INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(content_sha256, profile)
        );
        CREATE TABLE IF NOT EXISTS source_runs (
            run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
            source_id TEXT NOT NULL REFERENCES raw_sources(source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_source_runs_source ON source_runs(source_id);
    """)


def connect_catalog(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    create_schema(connection)
    create_catalog_schema(connection)
    return connection


def register_source(
    db_path: Path, content: bytes, filename: str, profile: str = "default",
    name: str | None = None, origin: str = "upload",
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError("Unknown processing profile.")
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.lower().endswith(".jsonl") or len(filename) > 180:
        raise ValueError("A .jsonl filename of at most 180 characters is required.")
    if len(content) > MAX_SOURCE_BYTES:
        raise ValueError("JSONL files must be at most 20 MiB.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("JSONL files must use UTF-8 encoding.") from exc
    # Match the text reader's physical lines; malformed JSON remains a pipeline concern.
    row_count = sum(bool(line.strip()) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    if not row_count:
        raise ValueError("The JSONL file has no nonblank records.")
    source_hash = hashlib.sha256(content).hexdigest()
    source_id = hashlib.sha256(f"{source_hash}:{profile}".encode()).hexdigest()[:32]
    with closing(connect_catalog(db_path)) as connection, connection:
        connection.execute(
            """INSERT INTO raw_sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(content_sha256, profile) DO NOTHING""",
            (source_id, (name or filename).strip() or filename, filename, origin, profile,
             source_hash, content, len(content), row_count, datetime.now(timezone.utc).isoformat()),
        )
        row = connection.execute(
            "SELECT * FROM raw_sources WHERE source_id = ?", (source_id,),
        ).fetchone()
    return source_metadata(row)


def source_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in (
        "source_id", "name", "filename", "origin", "profile", "content_sha256",
        "byte_count", "row_count", "created_at",
    )}
