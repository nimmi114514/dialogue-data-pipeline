from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from dialogue_pipeline import api
from dialogue_pipeline.__main__ import main
from dialogue_pipeline.catalog import connect_catalog
from dialogue_pipeline.pipeline import process_input
from dialogue_pipeline.storage import save_result


@pytest.fixture
def dashboard(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "APP_ROOT", tmp_path)
    monkeypatch.setattr(api, "UPLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(api, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "dashboard.sqlite")
    with TestClient(api.app) as client:
        yield client


def sample_bytes(count: int = 7, topic: str = "study") -> bytes:
    return "\n".join(json.dumps({
        "sample_id": f"s{index}", "group_id": f"g{index}", "topic": topic,
        "source": "synthetic", "language": "zh", "messages": [
            {"role": "user", "content": f"问题 {index}"},
            {"role": "assistant", "content": f"回答 {index}"},
        ],
    }, ensure_ascii=False) for index in range(count)).encode()


def upload(client: TestClient, content: bytes, profile: str = "default", endpoint: str = "/api/sources"):
    return client.post(endpoint, files={"file": ("sample.jsonl", content, "application/x-ndjson")}, data={"profile": profile})


def test_empty_catalog_and_unknown_source(dashboard):
    assert dashboard.get("/api/sources").json() == {"items": []}
    assert dashboard.get("/api/runs").json() == {"items": []}
    assert dashboard.post("/api/sources/missing/runs").status_code == 404
    assert dashboard.get("/api/sources/missing/download").status_code == 404


def test_split_failure_is_visible_in_history_and_report(dashboard):
    created = upload(dashboard, sample_bytes(1), endpoint="/api/runs").json()
    assert created["summary"]["status"] == "split_failed"
    assert created["summary"]["split_error"]
    history = dashboard.get("/api/runs").json()["items"]
    assert history[0]["status"] == "split_failed"
    report = dashboard.get(f"/api/runs/{created['run_id']}/report").json()
    assert report["status"] == "split_failed"
    assert report["checks"]["split_complete"] is False
    assert report["splits"]["unassigned"]["records"] == 1


def test_upload_save_rerun_and_download(dashboard):
    content = sample_bytes() + b"\n{broken\n"
    source = upload(dashboard, content).json()
    source_id = source["source_id"]
    assert source["row_count"] == 8
    assert source["byte_count"] == len(content)
    assert source["content_sha256"] == hashlib.sha256(content).hexdigest()
    assert source["origin"] == "upload"
    listed = dashboard.get("/api/sources").json()["items"]
    assert len(listed) == 1 and listed[0]["latest_run_id"] is None
    assert "content" not in listed[0]
    assert dashboard.get("/api/runs").json()["items"] == []
    download = dashboard.get(f"/api/sources/{source_id}/download")
    assert download.content == content
    assert "attachment" in download.headers["content-disposition"]

    first = dashboard.post(f"/api/sources/{source_id}/runs").json()
    assert first["summary"]["kept_count"] == 7
    assert first["summary"]["quarantined_count"] == 1
    # Database bytes, not the cache, are the authoritative rerun input.
    (api.UPLOAD_ROOT / source_id / "input.jsonl").unlink()
    second = dashboard.post(f"/api/sources/{source_id}/runs").json()
    assert second["run_id"] != first["run_id"]
    assert second["dataset_version"] == first["dataset_version"]
    history = dashboard.get("/api/runs", params={"source_id": source_id}).json()["items"]
    assert [run["run_id"] for run in history] == [second["run_id"], first["run_id"]]
    assert history[0]["source_name"] == "sample.jsonl"
    assert dashboard.get("/api/sources").json()["items"][0]["latest_run_id"] == second["run_id"]
    assert dashboard.get(f"/api/runs/{second['run_id']}/records").json()["total"] == 7


def test_content_profile_deduplication_and_run_filter(dashboard):
    content = sample_bytes(topic="other")
    default = upload(dashboard, content).json()
    assert upload(dashboard, content).json()["source_id"] == default["source_id"]
    public = upload(dashboard, content, "oasst1").json()
    assert public["source_id"] != default["source_id"]
    assert len(dashboard.get("/api/sources").json()["items"]) == 2
    strict_run = dashboard.post(f"/api/sources/{default['source_id']}/runs").json()
    public_run = dashboard.post(f"/api/sources/{public['source_id']}/runs").json()
    assert strict_run["summary"]["kept_count"] == 0
    assert strict_run["summary"]["rule_counts"]["UNKNOWN_TOPIC"] == 7
    assert public_run["summary"]["kept_count"] == 7
    assert "UNKNOWN_TOPIC" not in public_run["summary"]["rule_counts"]
    assert len(dashboard.get("/api/runs", params={"source_id": default["source_id"]}).json()["items"]) == 1


@pytest.mark.parametrize("filename,content,profile", [
    ("sample.txt", b"{}", "default"),
    ("empty.jsonl", b"\n \n", "default"),
    ("binary.jsonl", b"\xff", "default"),
    ("sample.jsonl", b"{}", "../../secret"),
])
def test_invalid_upload_does_not_create_source(dashboard, filename, content, profile):
    response = dashboard.post("/api/sources", files={"file": (filename, content)}, data={"profile": profile})
    assert response.status_code == 400
    assert dashboard.get("/api/sources").json()["items"] == []


def test_oversized_upload_and_safe_filename(dashboard, monkeypatch):
    monkeypatch.setattr(api, "MAX_SOURCE_BYTES", 10)
    assert upload(dashboard, b"x" * 11).status_code == 413
    assert dashboard.get("/api/sources").json()["items"] == []
    response = dashboard.post("/api/sources", files={"file": ("../../sample.jsonl", b"{}")})
    assert response.status_code == 200
    assert response.json()["filename"] == "sample.jsonl"


def test_pagination_covers_large_dataset_and_rejected(dashboard):
    content = sample_bytes(235) + b"\n{bad\n" * 115
    created = upload(dashboard, content, endpoint="/api/runs").json()
    run_id = created["run_id"]
    for kind, total, key in (("records", 235, "sample_id"), ("rejected", 115, "line_number")):
        all_items = []
        for offset in range(0, total, 50):
            page = dashboard.get(f"/api/runs/{run_id}/{kind}", params={"limit": 50, "offset": offset}).json()
            assert page["total"] == total
            assert len(page["items"]) == min(50, total - offset)
            all_items.extend(page["items"])
        assert len({item[key] for item in all_items}) == total
        assert dashboard.get(f"/api/runs/{run_id}/{kind}?offset=9999").json()["items"] == []
        assert dashboard.get(f"/api/runs/{run_id}/{kind}?offset=-1").status_code == 422
        assert dashboard.get(f"/api/runs/{run_id}/{kind}?limit=201").status_code == 422


def test_catalog_cli_persists_source_without_file_dependency(tmp_path):
    input_path = tmp_path / "public.jsonl"
    input_path.write_bytes(sample_bytes())
    db_path = tmp_path / "dashboard.sqlite"
    args = ["catalog-add", "--input", str(input_path), "--db", str(db_path),
            "--profile", "oasst1", "--origin", "public", "--name", "Public sample"]
    assert main(args) == 0
    assert main(args) == 0
    input_path.unlink()
    with closing(connect_catalog(db_path)) as connection:
        rows = connection.execute("SELECT * FROM raw_sources").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Public sample"
    assert rows[0]["content"] == sample_bytes()


def test_legacy_migration_is_idempotent_and_checks_hash(dashboard):
    input_path = api.UPLOAD_ROOT / "old-upload" / "input.jsonl"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(sample_bytes())
    config_path = Path("configs/default.json")
    config = json.loads(config_path.read_text())
    result = process_input(input_path, config_path, config)
    run_id = save_result(api.DB_PATH, result, config)
    api.migrate_uploads()
    api.migrate_uploads()
    sources = dashboard.get("/api/sources").json()["items"]
    assert len(sources) == 1
    assert dashboard.get(f"/api/runs/{run_id}").json()["source_id"] == sources[0]["source_id"]

    other_path = api.UPLOAD_ROOT / "changed" / "input.jsonl"
    other_path.parent.mkdir(parents=True)
    other_path.write_bytes(sample_bytes(8))
    other_result = process_input(other_path, config_path, config)
    changed_run = save_result(api.DB_PATH, other_result, config)
    other_path.write_bytes(b"{}")
    api.migrate_uploads()
    assert dashboard.get(f"/api/runs/{changed_run}").json()["source_id"] is None


def test_source_run_link_rolls_back_with_invalid_source(dashboard):
    input_path = api.APP_ROOT / "input.jsonl"
    input_path.write_bytes(sample_bytes())
    config_path = Path("configs/default.json")
    config = json.loads(config_path.read_text())
    result = process_input(input_path, config_path, config)
    with pytest.raises(sqlite3.IntegrityError):
        save_result(api.DB_PATH, result, config, source_id="missing")
    assert dashboard.get("/api/runs").json()["items"] == []
    with closing(connect_catalog(api.DB_PATH)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
