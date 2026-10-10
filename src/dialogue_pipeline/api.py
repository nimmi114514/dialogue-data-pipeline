from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any
import uuid

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .pipeline import process_input
from .storage import create_schema, save_result


APP_ROOT = Path("artifacts/web")
UPLOAD_ROOT = APP_ROOT / "uploads"
RUN_ROOT = APP_ROOT / "runs"
DB_PATH = APP_ROOT / "dashboard.sqlite"
DEFAULT_CONFIG = Path("configs/default.json")

app = FastAPI(title="dialogue-data-pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/runs")
def create_run(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename or not file.filename.endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="Only .jsonl uploads are supported.")

    run_id = uuid.uuid4().hex
    upload_dir = UPLOAD_ROOT / run_id
    output_dir = RUN_ROOT / run_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "input.jsonl"

    with input_path.open("wb") as file_obj:
        shutil.copyfileobj(file.file, file_obj)

    config = _load_config(DEFAULT_CONFIG)
    result = process_input(input_path, DEFAULT_CONFIG, config)
    _write_outputs(output_dir, result)
    db_run_id = save_result(DB_PATH, result, config)

    return {
        "run_id": db_run_id,
        "upload_id": run_id,
        "dataset_version": result.summary["dataset_version"],
        "summary": result.summary,
    }


@app.get("/api/runs")
def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
              runs.run_id,
              runs.dataset_version,
              runs.started_at,
              runs.finished_at,
              runs.status,
              datasets.summary_json
            FROM runs
            JOIN datasets USING (dataset_version)
            ORDER BY runs.started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"items": [_run_row(row) for row in rows]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT
              runs.run_id,
              runs.dataset_version,
              runs.started_at,
              runs.finished_at,
              runs.status,
              datasets.summary_json
            FROM runs
            JOIN datasets USING (dataset_version)
            WHERE runs.run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _run_row(row)


@app.get("/api/runs/{run_id}/records")
def get_records(
    run_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    dataset_version = _dataset_version_for_run(run_id)
    with _connect() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM records WHERE dataset_version = ?",
            (dataset_version,),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
              sample_id,
              group_id,
              topic,
              source,
              language,
              content_hash,
              char_count,
              leakage_group_id,
              split,
              line_number,
              messages_json,
              cleaning_events_json
            FROM records
            WHERE dataset_version = ?
            ORDER BY line_number
            LIMIT ? OFFSET ?
            """,
            (dataset_version, limit, offset),
        ).fetchall()
    return {
        "total": total,
        "items": [
            {
                "sample_id": row["sample_id"],
                "group_id": row["group_id"],
                "topic": row["topic"],
                "source": row["source"],
                "language": row["language"],
                "content_hash": row["content_hash"],
                "char_count": row["char_count"],
                "leakage_group_id": row["leakage_group_id"],
                "split": row["split"],
                "line_number": row["line_number"],
                "messages": json.loads(row["messages_json"]),
                "cleaning_events": json.loads(row["cleaning_events_json"]),
            }
            for row in rows
        ],
    }


@app.get("/api/runs/{run_id}/rejected")
def get_rejected(
    run_id: str,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    dataset_version = _dataset_version_for_run(run_id)
    where = "dataset_version = ? AND status != 'kept'"
    params: list[Any] = [dataset_version]
    if status:
        where += " AND status = ?"
        params.append(status)

    with _connect() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM dispositions WHERE {where}",
            params,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT
              line_number,
              status,
              reasons_json,
              canonical_sample_id,
              content_hash,
              raw_text,
              source_path
            FROM dispositions
            WHERE {where}
            ORDER BY line_number
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
    return {
        "total": total,
        "items": [
            {
                "line_number": row["line_number"],
                "status": row["status"],
                "reasons": json.loads(row["reasons_json"]),
                "canonical_sample_id": row["canonical_sample_id"],
                "content_hash": row["content_hash"],
                "raw_text": row["raw_text"],
                "source_path": row["source_path"],
            }
            for row in rows
        ],
    }


@app.get("/api/runs/{run_id}/stats/topic")
def topic_stats(run_id: str) -> dict[str, Any]:
    dataset_version = _dataset_version_for_run(run_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT topic AS name, COUNT(*) AS value
            FROM records
            WHERE dataset_version = ?
            GROUP BY topic
            ORDER BY value DESC, topic ASC
            """,
            (dataset_version,),
        ).fetchall()
    return {"items": [_name_value(row) for row in rows]}


@app.get("/api/runs/{run_id}/stats/status")
def status_stats(run_id: str) -> dict[str, Any]:
    dataset_version = _dataset_version_for_run(run_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT status AS name, COUNT(*) AS value
            FROM dispositions
            WHERE dataset_version = ?
            GROUP BY status
            ORDER BY value DESC, status ASC
            """,
            (dataset_version,),
        ).fetchall()
    return {"items": [_name_value(row) for row in rows]}


@app.get("/api/runs/{run_id}/stats/rules")
def rule_stats(run_id: str) -> dict[str, Any]:
    dataset_version = _dataset_version_for_run(run_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
              json_extract(reason.value, '$.rule_id') AS name,
              COUNT(*) AS value
            FROM dispositions
            JOIN json_each(dispositions.reasons_json) AS reason
            WHERE dataset_version = ?
              AND json_extract(reason.value, '$.rule_id') IS NOT NULL
            GROUP BY name
            ORDER BY value DESC, name ASC
            """,
            (dataset_version,),
        ).fetchall()
    return {"items": [_name_value(row) for row in rows]}


@app.get("/api/runs/{run_id}/stats/split")
def split_stats(run_id: str) -> dict[str, Any]:
    dataset_version = _dataset_version_for_run(run_id)
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT COALESCE(split, 'unassigned') AS name, COUNT(*) AS value
            FROM records
            WHERE dataset_version = ?
            GROUP BY name
            ORDER BY value DESC, name ASC
            """,
            (dataset_version,),
        ).fetchall()
    return {"items": [_name_value(row) for row in rows]}


def _load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as file_obj:
        config = json.load(file_obj)
    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="Config must be a JSON object.")
    return config


def _write_outputs(output_dir: Path, result: Any) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "cleaned.jsonl", result.cleaned_rows)
    _write_jsonl(output_dir / "accepted.jsonl", result.cleaned_rows)
    _write_jsonl(output_dir / "rejected.jsonl", result.rejected_rows)
    for split_name, rows in result.split_rows.items():
        _write_jsonl(output_dir / f"{split_name}.jsonl", rows)
    _write_json(output_dir / "summary.json", result.summary)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2, sort_keys=True)
        file_obj.write("\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file_obj.write("\n")


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="No dashboard database exists yet.")
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def _dataset_version_for_run(run_id: str) -> str:
    with _connect() as connection:
        row = connection.execute(
            "SELECT dataset_version FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return row["dataset_version"]


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "dataset_version": row["dataset_version"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "summary": json.loads(row["summary_json"]),
    }


def _name_value(row: sqlite3.Row) -> dict[str, Any]:
    return {"name": row["name"], "value": row["value"]}
