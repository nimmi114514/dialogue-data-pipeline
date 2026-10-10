from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from .pipeline import PipelineResult


def save_result(db_path: Path, result: PipelineResult, config: dict[str, Any]) -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    started_at = _utc_now()

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        create_schema(connection)
        with connection:
            _upsert_dataset(connection, result, config)
            _replace_records(connection, result)
            _replace_dispositions(connection, result)
            connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    dataset_version,
                    started_at,
                    finished_at,
                    status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    result.summary["dataset_version"],
                    started_at,
                    _utc_now(),
                    result.summary["status"],
                ),
            )
    return run_id


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            dataset_version TEXT PRIMARY KEY,
            source_file_hash TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            pipeline_revision TEXT NOT NULL,
            status TEXT NOT NULL,
            config_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            dataset_version TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (dataset_version) REFERENCES datasets(dataset_version)
        );

        CREATE TABLE IF NOT EXISTS records (
            dataset_version TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            topic TEXT NOT NULL,
            source TEXT NOT NULL,
            group_id TEXT NOT NULL,
            language TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            source_file_hash TEXT NOT NULL,
            messages_json TEXT NOT NULL,
            record_json TEXT NOT NULL,
            cleaning_events_json TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            leakage_group_id TEXT,
            split TEXT,
            PRIMARY KEY (dataset_version, sample_id),
            FOREIGN KEY (dataset_version) REFERENCES datasets(dataset_version)
        );

        CREATE TABLE IF NOT EXISTS dispositions (
            dataset_version TEXT NOT NULL,
            source_file_hash TEXT NOT NULL,
            line_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            canonical_sample_id TEXT,
            content_hash TEXT,
            raw_text TEXT NOT NULL,
            source_path TEXT NOT NULL,
            PRIMARY KEY (dataset_version, source_file_hash, line_number),
            FOREIGN KEY (dataset_version) REFERENCES datasets(dataset_version)
        );

        CREATE INDEX IF NOT EXISTS idx_records_dataset_topic
            ON records(dataset_version, topic);

        CREATE INDEX IF NOT EXISTS idx_dispositions_dataset_status
            ON dispositions(dataset_version, status);
        """
    )
    _ensure_column(connection, "records", "leakage_group_id", "TEXT")
    _ensure_column(connection, "records", "split", "TEXT")


def _upsert_dataset(
    connection: sqlite3.Connection,
    result: PipelineResult,
    config: dict[str, Any],
) -> None:
    now = _utc_now()
    connection.execute(
        """
        INSERT INTO datasets (
            dataset_version,
            source_file_hash,
            config_hash,
            pipeline_revision,
            status,
            config_json,
            summary_json,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(dataset_version) DO UPDATE SET
            status = excluded.status,
            config_json = excluded.config_json,
            summary_json = excluded.summary_json,
            updated_at = excluded.updated_at
        """,
        (
            result.summary["dataset_version"],
            result.summary["source_file_hash"],
            result.summary["config_hash"],
            result.summary["pipeline_revision"],
            result.summary["status"],
            _to_json(config),
            _to_json(result.summary),
            now,
            now,
        ),
    )


def _replace_records(connection: sqlite3.Connection, result: PipelineResult) -> None:
    dataset_version = result.summary["dataset_version"]
    connection.execute("DELETE FROM records WHERE dataset_version = ?", (dataset_version,))
    connection.executemany(
        """
        INSERT INTO records (
            dataset_version,
            sample_id,
            content_hash,
            topic,
            source,
            group_id,
            language,
            line_number,
            source_file_hash,
            messages_json,
            record_json,
            cleaning_events_json,
            char_count,
            leakage_group_id,
            split
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                dataset_version,
                row["sample_id"],
                row["content_hash"],
                row["topic"],
                row["source"],
                row["group_id"],
                row["language"],
                row["line_number"],
                row["source_file_hash"],
                _to_json(row["record"]["messages"]),
                _to_json(row["record"]),
                _to_json(row["cleaning_events"]),
                row["char_count"],
                row["leakage_group_id"],
                row["split"],
            )
            for row in result.cleaned_rows
        ],
    )


def _replace_dispositions(connection: sqlite3.Connection, result: PipelineResult) -> None:
    dataset_version = result.summary["dataset_version"]
    connection.execute("DELETE FROM dispositions WHERE dataset_version = ?", (dataset_version,))
    connection.executemany(
        """
        INSERT INTO dispositions (
            dataset_version,
            source_file_hash,
            line_number,
            status,
            reasons_json,
            canonical_sample_id,
            content_hash,
            raw_text,
            source_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                dataset_version,
                row["source_file_hash"],
                row["line_number"],
                row["status"],
                _to_json(row["reasons"]),
                row["canonical_sample_id"],
                row["content_hash"],
                row["raw_text"],
                row["source_path"],
            )
            for row in result.disposition_rows
        ],
    )


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
