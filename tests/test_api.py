import json
from pathlib import Path

from fastapi.testclient import TestClient

from dialogue_pipeline import api


def test_api_upload_and_query_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "APP_ROOT", tmp_path)
    monkeypatch.setattr(api, "UPLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(api, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "dashboard.sqlite")

    client = TestClient(api.app)
    input_bytes = Path("data/samples/raw_dialogues.jsonl").read_bytes()
    response = client.post(
        "/api/runs",
        files={"file": ("raw_dialogues.jsonl", input_bytes, "application/jsonl")},
    )

    assert response.status_code == 200
    created = response.json()
    run_id = created["run_id"]
    assert created["summary"]["kept_count"] == 13
    assert created["summary"]["duplicate_count"] == 1
    assert created["summary"]["quarantined_count"] == 10

    records = client.get(f"/api/runs/{run_id}/records").json()
    rejected = client.get(f"/api/runs/{run_id}/rejected").json()
    topic_stats = client.get(f"/api/runs/{run_id}/stats/topic").json()
    status_stats = client.get(f"/api/runs/{run_id}/stats/status").json()
    rule_stats = client.get(f"/api/runs/{run_id}/stats/rules").json()
    runs = client.get("/api/runs").json()

    assert records["total"] == 13
    assert rejected["total"] == 11
    assert {"name": "study", "value": 3} in topic_stats["items"]
    assert {"name": "kept", "value": 13} in status_stats["items"]
    assert {"name": "SAMPLE_ID_CONFLICT", "value": 2} in rule_stats["items"]
    assert runs["items"][0]["run_id"] == run_id


def test_api_rejects_non_jsonl_upload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(api, "APP_ROOT", tmp_path)
    monkeypatch.setattr(api, "UPLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(api, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "dashboard.sqlite")

    client = TestClient(api.app)
    response = client.post(
        "/api/runs",
        files={"file": ("sample.txt", b"{}", "text/plain")},
    )

    assert response.status_code == 400
    assert "jsonl" in json.dumps(response.json())
