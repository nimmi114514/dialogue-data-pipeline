from __future__ import annotations

import json
import hashlib
from contextlib import asynccontextmanager, closing
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
from urllib.parse import quote
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .export import write_outputs
from .pipeline import process_input
from .report import load_report, render_markdown
from .storage import save_result
from .catalog import MAX_SOURCE_BYTES, PROFILES, connect_catalog, register_source, source_metadata


APP_ROOT = Path("artifacts/web")
UPLOAD_ROOT = APP_ROOT / "uploads"
RUN_ROOT = APP_ROOT / "runs"
DB_PATH = APP_ROOT / "dashboard.sqlite"

@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_uploads()
    yield


app = FastAPI(title="dialogue-data-pipeline API", lifespan=lifespan)
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
def create_run(file: UploadFile = File(...), profile: str = Form(default="default")) -> dict[str, Any]:
    source = _register_upload(file, profile)
    return run_source(source["source_id"])


@app.post("/api/sources")
def upload_source(file: UploadFile = File(...), profile: str = Form(default="default")) -> dict[str, Any]:
    return _register_upload(file, profile)


def _register_upload(file: UploadFile, profile: str) -> dict[str, Any]:
    content = file.file.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="JSONL files must be at most 20 MiB.")
    try:
        return register_source(DB_PATH, content, file.filename or "", profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sources")
def list_sources() -> dict[str, Any]:
    with closing(_connect()) as connection:
        rows = connection.execute("""
            SELECT source_id, name, filename, origin, profile, content_sha256,
                   byte_count, row_count, created_at,
                   (SELECT sr.run_id FROM source_runs sr JOIN runs r USING (run_id)
                    WHERE sr.source_id = s.source_id
                    ORDER BY r.started_at DESC, r.rowid DESC LIMIT 1) AS latest_run_id
            FROM raw_sources s ORDER BY created_at DESC, source_id
        """).fetchall()
    return {"items": [{**source_metadata(row), "latest_run_id": row["latest_run_id"]} for row in rows]}


@app.get("/api/sources/{source_id}/download")
def download_source(source_id: str) -> Response:
    source = _source(source_id)
    return Response(
        content=source["content"], media_type="application/x-ndjson",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(source['filename'], safe='')}"},
    )


@app.post("/api/sources/{source_id}/runs")
def run_source(source_id: str) -> dict[str, Any]:
    source = _source(source_id)
    config_path = PROFILES.get(source["profile"])
    if config_path is None:
        raise HTTPException(status_code=400, detail="Unknown processing profile.")
    upload_id = uuid.uuid4().hex
    upload_dir = UPLOAD_ROOT / source_id
    output_dir = RUN_ROOT / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    input_path = upload_dir / "input.jsonl"
    # Publish a complete copy; concurrent reruns never read a partly written input.
    with tempfile.NamedTemporaryFile(dir=upload_dir, delete=False) as file_obj:
        temporary_path = Path(file_obj.name)
        try:
            file_obj.write(source["content"])
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    try:
        temporary_path.replace(input_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    config = _load_config(config_path)
    result = process_input(input_path, config_path, config)
    db_run_id = save_result(DB_PATH, result, config, source_id=source_id)
    write_outputs(output_dir, result, config, report=load_report(DB_PATH, result.summary["dataset_version"]))

    return {
        "run_id": db_run_id,
        "upload_id": upload_id,
        "source_id": source_id,
        "dataset_version": result.summary["dataset_version"],
        "summary": result.summary,
    }


@app.get("/api/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100), source_id: str | None = None,
) -> dict[str, Any]:
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT
              runs.run_id,
              runs.dataset_version,
              runs.started_at,
              runs.finished_at,
              runs.status,
              source_runs.source_id,
              raw_sources.name AS source_name,
              datasets.summary_json
            FROM runs
            JOIN datasets USING (dataset_version)
            LEFT JOIN source_runs USING (run_id)
            LEFT JOIN raw_sources USING (source_id)
            WHERE (? IS NULL OR source_runs.source_id = ?)
            ORDER BY runs.started_at DESC, runs.rowid DESC
            LIMIT ?
            """,
            (source_id, source_id, limit),
        ).fetchall()
    return {"items": [_run_row(row) for row in rows]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    with closing(_connect()) as connection:
        row = connection.execute(
            """
            SELECT
              runs.run_id,
              runs.dataset_version,
              runs.started_at,
              runs.finished_at,
              runs.status,
              source_runs.source_id,
              raw_sources.name AS source_name,
              datasets.summary_json
            FROM runs
            JOIN datasets USING (dataset_version)
            LEFT JOIN source_runs USING (run_id)
            LEFT JOIN raw_sources USING (source_id)
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
    with closing(_connect()) as connection:
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

    with closing(_connect()) as connection:
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
    with closing(_connect()) as connection:
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
    with closing(_connect()) as connection:
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
    with closing(_connect()) as connection:
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
    with closing(_connect()) as connection:
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


@app.get("/api/runs/{run_id}/report")
def get_report(run_id: str, format: str = Query(default="json", pattern="^(json|md)$")) -> Response:
    dataset_version = _dataset_version_for_run(run_id)
    report = load_report(DB_PATH, dataset_version)
    content = render_markdown(report) if format == "md" else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return Response(
        content=content,
        media_type="text/markdown" if format == "md" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="quality_report.{format}"'},
    )


def _connect() -> sqlite3.Connection:
    return connect_catalog(DB_PATH)


def _source(source_id: str) -> sqlite3.Row:
    with closing(_connect()) as connection:
        row = connection.execute("SELECT * FROM raw_sources WHERE source_id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return row


def migrate_uploads() -> None:
    """Register recoverable uploads from dashboards created before the source catalog."""
    with closing(_connect()) as connection:
        rows = connection.execute("""
            SELECT r.run_id, d.summary_json FROM runs r JOIN datasets d USING (dataset_version)
            LEFT JOIN source_runs sr USING (run_id) WHERE sr.run_id IS NULL
        """).fetchall()
    for row in rows:
        summary = json.loads(row["summary_json"])
        input_path = Path(summary.get("input_path", ""))
        if not input_path.resolve().is_relative_to(UPLOAD_ROOT.resolve()) or not input_path.is_file():
            continue
        profile = next((key for key, path in PROFILES.items() if str(path) == summary.get("config_path")), None)
        if profile is None:
            continue
        with input_path.open("rb") as file_obj:
            content = file_obj.read(MAX_SOURCE_BYTES + 1)
        if hashlib.sha256(content).hexdigest() != summary.get("source_file_hash"):
            continue
        try:
            source = register_source(DB_PATH, content, f"upload-{summary['source_file_hash'][:8]}.jsonl", profile)
        except ValueError:
            continue
        with closing(_connect()) as connection, connection:
            connection.execute(
                "INSERT OR IGNORE INTO source_runs (run_id, source_id) VALUES (?, ?)",
                (row["run_id"], source["source_id"]),
            )


def _dataset_version_for_run(run_id: str) -> str:
    with closing(_connect()) as connection:
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
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "summary": json.loads(row["summary_json"]),
    }


def _name_value(row: sqlite3.Row) -> dict[str, Any]:
    return {"name": row["name"], "value": row["value"]}
