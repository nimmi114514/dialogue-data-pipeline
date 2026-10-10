import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


@pytest.mark.parametrize("command", ["check", "run"])
@pytest.mark.parametrize("strict", [False, True])
def test_split_failure_returns_nonzero_and_persists_diagnostics(tmp_path, command, strict):
    input_path = tmp_path / "single-group.jsonl"
    original = Path("data/samples/raw_dialogues.jsonl").read_text(encoding="utf-8").splitlines()[0]
    input_path.write_text(original + "\n", encoding="utf-8")
    output = tmp_path / "output"
    db_path = tmp_path / "pipeline.sqlite"
    args = [sys.executable, "-m", "dialogue_pipeline", command, "--input", str(input_path), "--output", str(output)]
    if command == "run":
        args.extend(["--db", str(db_path)])
    if strict:
        args.append("--strict")
    process = subprocess.run(args, capture_output=True, text=True)
    assert process.returncode == 3
    assert "split failed" in process.stdout
    assert "至少需要 3 个独立泄漏组" in process.stderr
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    report = json.loads((output / "quality_report.json").read_text(encoding="utf-8"))
    assert summary["status"] == report["status"] == "split_failed"
    assert summary["split_error"] and not report["checks"]["split_complete"]
    assert report["splits"]["unassigned"]["records"] == 1
    assert summary["split_counts"] == {"train": 0, "validation": 0, "test": 0}
    assert (output / "cleaned.jsonl").read_bytes()
    for split in ("train", "validation", "test"):
        assert (output / f"{split}.jsonl").read_bytes() == b""
    if command == "run":
        with sqlite3.connect(db_path) as connection:
            assert connection.execute("SELECT status FROM runs").fetchone()[0] == "split_failed"
            assert connection.execute("SELECT status FROM datasets").fetchone()[0] == "split_failed"
