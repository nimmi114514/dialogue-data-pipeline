import json
from pathlib import Path
import sqlite3

import pytest

from dialogue_pipeline.__main__ import main
from dialogue_pipeline.pipeline import process_input
from dialogue_pipeline.report import build_report, load_report, render_markdown
from dialogue_pipeline.storage import save_result


CONFIG_PATH = Path("configs/default.json")


def process(path: Path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    result = process_input(path, CONFIG_PATH, config)
    return result, config


def test_report_counts_scopes_and_sql_roundtrip(tmp_path: Path) -> None:
    result, config = process(Path("data/samples/raw_dialogues.jsonl"))
    report = build_report(result.summary, result.cleaned_rows, result.disposition_rows, config)
    assert report["counts"] == {
        "candidate_lines": 24, "blank_lines": 1, "kept": 13,
        "duplicate": 1, "quarantined": 10, "conflict_lines": 2,
    }
    assert report["metrics"]["usable_rate"] == {"numerator": 13, "denominator": 24, "value": 13 / 24}
    assert report["metrics"]["human_review_coverage"]["value"] == 0
    assert report["metrics"]["human_accept_rate"]["value"] is None
    assert report["rule_counts"]["INVALID_ROLE_SEQUENCE"] == 3
    assert sum(report["rule_counts"].values()) > 11
    assert sum(report["dialogue_chars"]["histogram"].values()) == 13
    assert report["dialogue_chars"]["max"] == max(row["char_count"] for row in result.cleaned_rows)
    assert sum(split["groups"] for split in report["splits"].values()) == 11
    assert all(report["checks"].values())
    assert len(report["observations"]) >= 3
    assert report["human_review"]["decision_counts"] == {"accept": 0, "reject": 0, "unsure": 0}
    assert all({"numerator", "denominator", "meaning", "limitation"} <= observation.keys() for observation in report["observations"])

    db = tmp_path / "pipeline.sqlite"
    save_result(db, result, config)
    before = db.read_bytes()
    version = result.summary["dataset_version"]
    assert load_report(db, version) == report
    assert db.read_bytes() == before
    with sqlite3.connect(db) as connection:
        sql_topics = dict(connection.execute("SELECT topic, COUNT(*) FROM records GROUP BY topic"))
        sql_rules = dict(connection.execute("SELECT json_extract(reason.value, '$.rule_id'), COUNT(*) FROM dispositions JOIN json_each(reasons_json) AS reason GROUP BY 1"))
    assert report["topic_counts"] == sql_topics
    assert report["rule_counts"] == sql_rules


@pytest.mark.parametrize("text,candidate_count,quarantined", [("\n  \n", 0, 0), ("not-json\n{}\n", 2, 2)])
def test_empty_or_all_rejected_has_no_fabricated_ratios(tmp_path: Path, text: str, candidate_count: int, quarantined: int) -> None:
    path = tmp_path / "input.jsonl"
    path.write_text(text, encoding="utf-8")
    result, config = process(path)
    report = build_report(result.summary, result.cleaned_rows, result.disposition_rows, config)
    assert report["counts"]["candidate_lines"] == candidate_count
    assert report["counts"]["quarantined"] == quarantined
    assert report["metrics"]["usable_rate"]["value"] == (0 if candidate_count else None)
    assert report["metrics"]["human_review_coverage"]["value"] is None
    assert report["dialogue_chars"]["mean"] is None
    assert report["splits"]["train"]["record_share"]["value"] is None
    assert "N/A" in render_markdown(report)
    assert all(report["checks"].values())


def test_report_exposes_split_failure_and_overlap(tmp_path: Path) -> None:
    path = tmp_path / "small.jsonl"
    path.write_text(Path("data/samples/raw_dialogues.jsonl").read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    result, config = process(path)
    report = build_report(result.summary, result.cleaned_rows, result.disposition_rows, config)
    assert report["split_error"]
    assert report["splits"]["unassigned"]["records"] == 1
    assert not report["checks"]["split_complete"]
    assert "切分未完成" in render_markdown(report)

    rows = [dict(result.cleaned_rows[0], split=name, leakage_group_id="lg_shared") for name in ("train", "test")]
    report = build_report(result.summary, rows, result.disposition_rows, config)
    assert not report["checks"]["kept_accounting"]
    assert not report["checks"]["no_group_overlap"]
    assert not report["checks"]["no_content_hash_overlap"]


def test_cli_reports_existing_version_without_raw_file(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jsonl"
    input_path.write_bytes(Path("data/samples/raw_dialogues.jsonl").read_bytes())
    output = tmp_path / "run"
    db = tmp_path / "pipeline.sqlite"
    assert main(["run", "--input", str(input_path), "--output", str(output), "--db", str(db)]) == 0
    version = json.loads((output / "summary.json").read_text())["dataset_version"]
    input_path.unlink()
    before = db.read_bytes()
    report_dir = tmp_path / "report"
    assert main(["report", "--db", str(db), "--version", version, "--output", str(report_dir)]) == 0
    assert (output / "quality_report.json").read_bytes() == (report_dir / "quality_report.json").read_bytes()
    assert (output / "quality_report.md").read_bytes() == (report_dir / "quality_report.md").read_bytes()
    assert db.read_bytes() == before

    assert main(["report", "--db", str(db), "--version", "missing", "--output", str(tmp_path / "bad")]) == 1
    assert not (tmp_path / "bad").exists()
    missing_db = tmp_path / "missing.sqlite"
    assert main(["report", "--db", str(missing_db), "--version", version, "--output", str(report_dir)]) == 1
    assert not missing_db.exists()


def test_markdown_escapes_source_table_cells() -> None:
    result, config = process(Path("data/samples/raw_dialogues.jsonl"))
    report = build_report(result.summary, result.cleaned_rows, result.disposition_rows, config)
    report["source_counts"] = {"<script>bad</script>|x\ny": 1}
    markdown = render_markdown(report)
    assert "<script>" not in markdown
    assert "&lt;script>bad&lt;/script>&#124;x y" in markdown


def test_partial_split_config_uses_pipeline_defaults() -> None:
    result, config = process(Path("data/samples/raw_dialogues.jsonl"))
    config["split_ratios"] = {"train": 1}
    report = build_report(result.summary, result.cleaned_rows, result.disposition_rows, config)
    assert report["splits"]["train"]["target_share"] == pytest.approx(1 / 1.2)
    assert report["splits"]["validation"]["target_share"] == pytest.approx(0.1 / 1.2)
    assert report["splits"]["unassigned"]["target_share"] is None
