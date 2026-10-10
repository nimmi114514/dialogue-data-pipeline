import csv
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from dialogue_pipeline.__main__ import main
from dialogue_pipeline.pipeline import process_input
from dialogue_pipeline.report import load_report
from dialogue_pipeline.review import LABEL_FIELDS, export_reviewed, export_template, import_labels, replay_labels
from dialogue_pipeline.storage import LABELS_SCHEMA, ensure_labels_schema, load_dataset, save_result


@pytest.fixture
def dataset(tmp_path):
    config_path = Path("configs/default.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = process_input(Path("data/samples/raw_dialogues.jsonl"), config_path, config)
    db = tmp_path / "review.sqlite"
    save_result(db, result, config)
    return db, result.summary["dataset_version"], result, config


def label(row, version, origin="human", decision="accept"):
    # Human labels here are test fixtures, never exported as demonstration data.
    return dict(zip(LABEL_FIELDS, (
        version, row["sample_id"], row["content_hash"], "yes", "yes",
        decision, "test_reviewer", origin, "test fixture" if decision != "accept" else "",
    )))


def write_csv(path, labels):
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerows(labels)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_template_is_unreviewed_and_has_full_dialogue_context(dataset, tmp_path):
    db, version, result, _ = dataset
    output = tmp_path / "template"
    assert export_template(db, version, output) == 13
    with (output / "labels_template.csv").open(encoding="utf-8", newline="") as file_obj:
        labels = list(csv.DictReader(file_obj))
    assert len(labels) == 13
    assert all(not row["decision"] and not row["label_origin"] for row in labels)
    samples = read_jsonl(output / "review_samples.jsonl")
    assert samples[0]["messages"] == result.cleaned_rows[0]["record"]["messages"]
    assert import_labels(db, version, output / "labels_template.csv") == 0
    assert load_dataset(db, version)["labels"] == []


def test_project_review_migrates_old_database_and_keeps_export_policies_separate(dataset, tmp_path):
    db, version, result, _ = dataset
    train = [row for row in result.cleaned_rows if row["split"] == "train"]
    csv_path = tmp_path / "labels.csv"
    write_csv(csv_path, [label(train[0], version)])
    import_labels(db, version, csv_path)
    with sqlite3.connect(db) as connection:
        connection.execute("ALTER TABLE labels RENAME TO backup_labels")
        connection.execute(LABELS_SCHEMA.replace("'human', 'project_review',", "'human',"))
        connection.execute("INSERT INTO labels SELECT * FROM backup_labels")
        connection.execute("DROP TABLE backup_labels")
    write_csv(csv_path, [label(train[1], version, origin="project_review")])
    assert import_labels(db, version, csv_path) == 1
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == 2
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'labels_legacy'").fetchone() is None
    report = load_report(db, version)
    assert report["human_review"]["reviewed_count"] == 1
    assert report["project_review"]["reviewed_count"] == 1
    default = tmp_path / "default"
    export_reviewed(db, version, default)
    assert read_jsonl(default / "sft_train.sidecar.jsonl")[0]["sample_id"] == train[0]["sample_id"]
    project = tmp_path / "project"
    manifest = export_reviewed(db, version, project, label_origin="project_review")
    assert manifest["label_origin"] == "project_review"
    assert manifest["reviewed_counts"] == {"train": 1, "validation": 0, "test": 0}
    assert read_jsonl(project / "sft_train.sidecar.jsonl")[0]["sample_id"] == train[1]["sample_id"]
    assert read_jsonl(project / "reviewed_train.jsonl")[0]["label_origin"] == "project_review"
    with pytest.raises(ValueError, match="label_origin"):
        export_reviewed(db, version, tmp_path / "demo", label_origin="synthetic_demo")


@pytest.mark.parametrize("corruption", [None, "source", "content", "missing", "duplicate", "type"])
def test_replay_binds_only_matching_content_and_preserves_output_on_failure(dataset, tmp_path, corruption):
    db, version, result, _ = dataset
    row = label(result.cleaned_rows[0], "old-version", origin="project_review")
    bundle = {"source_file_hash": result.summary["source_file_hash"], "labels": [row]}
    if corruption == "source":
        bundle["source_file_hash"] = "wrong"
    elif corruption == "content":
        row["content_hash"] = "wrong"
    elif corruption == "missing":
        del row["decision"]
    elif corruption == "duplicate":
        bundle["labels"].append(row)
    elif corruption == "type":
        row["notes"] = None
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    output = tmp_path / "bound.csv"
    output.write_text("previous", encoding="utf-8")
    if corruption:
        with pytest.raises(ValueError):
            replay_labels(db, version, path, output)
        assert output.read_text() == "previous"
        assert not list(tmp_path.glob(".labels-*"))
    else:
        assert main(["labels-replay", "--db", str(db), "--version", version,
                     "--input", str(path), "--output", str(output)]) == 0
        assert import_labels(db, version, output) == 1
        assert load_dataset(db, version)["labels"][0]["dataset_version"] == version


def test_schema_migration_failure_restores_legacy_table(dataset):
    db, version, result, _ = dataset
    with sqlite3.connect(db) as connection:
        connection.execute("DROP TABLE labels")
        connection.execute(LABELS_SCHEMA.replace("'human', 'project_review',", "'human',"))
        row = label(result.cleaned_rows[0], version)
        connection.execute("INSERT INTO labels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == "INSERT INTO labels SELECT * FROM labels_legacy":
                raise sqlite3.OperationalError("simulated copy failure")
            return super().execute(sql, *args)

    with sqlite3.connect(db, factory=FailingConnection) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.OperationalError, match="copy failure"):
            ensure_labels_schema(connection)
        schema = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'labels'").fetchone()[0]
        assert "project_review" not in schema
        assert connection.execute("SELECT sample_id FROM labels").fetchone()[0] == row["sample_id"]
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'labels_legacy'").fetchone() is None


@pytest.mark.parametrize("field,value", [
    ("dataset_version", "old-version"), ("content_hash", "old-hash"),
    ("sample_id", "missing"), ("decision", "maybe"), ("relevant", "no"),
    ("complete", "unsure"), ("reviewer", ""), ("label_origin", "ai"),
])
def test_invalid_batch_preserves_existing_labels(dataset, tmp_path, field, value):
    db, version, result, _ = dataset
    csv_path = tmp_path / "labels.csv"
    initial = label(result.cleaned_rows[0], version)
    write_csv(csv_path, [initial])
    import_labels(db, version, csv_path)
    before = load_dataset(db, version)["labels"]
    first = {**initial, "notes": "must roll back"}
    invalid = {**label(result.cleaned_rows[1], version), field: value}
    write_csv(csv_path, [first, invalid])
    with pytest.raises(ValueError, match="CSV line"):
        import_labels(db, version, csv_path)
    assert load_dataset(db, version)["labels"] == before


def test_duplicate_labels_and_missing_rejection_notes_fail(dataset, tmp_path):
    db, version, result, _ = dataset
    csv_path = tmp_path / "labels.csv"
    row = label(result.cleaned_rows[0], version)
    write_csv(csv_path, [row, row])
    with pytest.raises(ValueError, match="duplicate label"):
        import_labels(db, version, csv_path)
    row.update(decision="reject", notes="")
    write_csv(csv_path, [row])
    with pytest.raises(ValueError, match="requires notes"):
        import_labels(db, version, csv_path)
    assert load_dataset(db, version)["labels"] == []


def test_database_write_failure_rolls_back_entire_batch(dataset, tmp_path):
    db, version, result, _ = dataset
    rows = [label(row, version) for row in result.cleaned_rows[:2]]
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TRIGGER fail_second BEFORE INSERT ON labels "
            "WHEN NEW.sample_id != (SELECT sample_id FROM records ORDER BY line_number LIMIT 1) "
            "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
        )
    csv_path = tmp_path / "labels.csv"
    write_csv(csv_path, rows)
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        import_labels(db, version, csv_path)
    assert load_dataset(db, version)["labels"] == []


def test_import_is_idempotent_and_survives_processing_rerun(dataset, tmp_path):
    db, version, result, config = dataset
    csv_path = tmp_path / "labels.csv"
    write_csv(csv_path, [label(result.cleaned_rows[0], version)])
    assert import_labels(db, version, csv_path) == 1
    before = load_report(db, version)
    assert import_labels(db, version, csv_path) == 1
    save_result(db, result, config)
    assert load_report(db, version) == before
    output = tmp_path / "rerun"
    assert main(["run", "--input", "data/samples/raw_dialogues.jsonl", "--output", str(output), "--db", str(db)]) == 0
    assert json.loads((output / "quality_report.json").read_text(encoding="utf-8")) == before


def test_human_metrics_and_training_export_exclude_demo_and_unreviewed(dataset, tmp_path):
    db, version, result, _ = dataset
    train = [row for row in result.cleaned_rows if row["split"] == "train"]
    validation = next(row for row in result.cleaned_rows if row["split"] == "validation")
    test = next(row for row in result.cleaned_rows if row["split"] == "test")
    rows = [label(train[0], version), label(train[1], version, decision="reject"),
            label(train[2], version, origin="synthetic_demo"), label(validation, version), label(test, version)]
    csv_path = tmp_path / "labels.csv"
    write_csv(csv_path, rows)
    import_labels(db, version, csv_path)
    report = load_report(db, version)
    assert report["metrics"]["human_review_coverage"]["value"] == 4 / 13
    assert report["metrics"]["human_accept_rate"]["value"] == 3 / 4
    assert report["human_review"]["decision_counts"] == {"accept": 3, "reject": 1, "unsure": 0}
    assert report["human_review"]["demo_count"] == 1
    output = tmp_path / "reviewed"
    manifest = export_reviewed(db, version, output)
    assert manifest["reviewed_counts"] == {"train": 1, "validation": 1, "test": 1}
    training = read_jsonl(output / "sft_train.jsonl")
    assert training == [{"messages": train[0]["record"]["messages"]}]
    sidecar = read_jsonl(output / "sft_train.sidecar.jsonl")
    assert sidecar[0]["sample_id"] == train[0]["sample_id"]
    assert sidecar[0]["sft_line_number"] == 1
    assert manifest["labels_hash"] == report["human_review"]["labels_hash"]
    for filename, digest in manifest["output_sha256"].items():
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == digest
    second = tmp_path / "reviewed-again"
    assert export_reviewed(db, version, second) == manifest
    for path in output.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        export_reviewed(db, version, output)
    rows[0]["notes"] = "updated judgment"
    write_csv(csv_path, rows)
    import_labels(db, version, csv_path)
    changed = export_reviewed(db, version, tmp_path / "changed")
    assert changed["review_version"] != manifest["review_version"]


def test_demo_only_exports_empty_training_files(dataset, tmp_path):
    db, version, result, _ = dataset
    csv_path = tmp_path / "demo.csv"
    write_csv(csv_path, [label(result.cleaned_rows[0], version, origin="synthetic_demo")])
    import_labels(db, version, csv_path)
    report = load_report(db, version)
    assert report["human_review"]["status"] == "demo_only"
    assert report["metrics"]["human_review_coverage"]["value"] == 0
    assert report["metrics"]["human_accept_rate"]["value"] is None
    output = tmp_path / "demo-export"
    manifest = export_reviewed(db, version, output)
    assert manifest["status"] == "no_human_accepted_samples"
    assert (output / "sft_train.jsonl").read_bytes() == b""
    assert (output / "reviewed_train.jsonl").read_bytes() == b""


def test_export_refuses_unassigned_splits(tmp_path):
    input_path = tmp_path / "small.jsonl"
    input_path.write_text(Path("data/samples/raw_dialogues.jsonl").read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    config_path = Path("configs/default.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = process_input(input_path, config_path, config)
    db = tmp_path / "small.sqlite"
    save_result(db, result, config)
    output = tmp_path / "export"
    with pytest.raises(ValueError, match="complete split"):
        export_reviewed(db, result.summary["dataset_version"], output)
    assert not output.exists()


def test_review_commands_and_invalid_database(dataset, tmp_path):
    db, version, _, _ = dataset
    output = tmp_path / "template"
    common = ["--db", str(db), "--version", version]
    assert main(["labels-template", *common, "--output", str(output)]) == 0
    assert main(["labels-import", *common, "--input", str(output / "labels_template.csv")]) == 0
    assert main(["export-reviewed", *common, "--output", str(tmp_path / "export")]) == 0
    missing = tmp_path / "missing.sqlite"
    assert main(["labels-import", "--db", str(missing), "--version", version, "--input", str(output / "labels_template.csv")]) == 1
    assert not missing.exists()


def test_export_failure_does_not_publish_partial_directory(dataset, tmp_path, monkeypatch):
    from dialogue_pipeline import review

    db, version, _, _ = dataset
    output = tmp_path / "failed-export"

    def fail_write(*args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(review, "_write_jsonl", fail_write)
    with pytest.raises(OSError, match="simulated disk"):
        export_reviewed(db, version, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".review-*"))


def test_stale_stored_label_is_reported_and_blocks_export(dataset, tmp_path):
    db, version, result, _ = dataset
    csv_path = tmp_path / "labels.csv"
    write_csv(csv_path, [label(result.cleaned_rows[0], version)])
    import_labels(db, version, csv_path)
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE labels SET content_hash = 'stale'")
    report = load_report(db, version)
    assert report["human_review"]["reviewed_count"] == 0
    assert report["human_review"]["stale_label_count"] == 1
    assert not report["checks"]["valid_label_hashes"]
    with pytest.raises(ValueError, match="Stale labels"):
        export_reviewed(db, version, tmp_path / "stale-export")


@pytest.mark.parametrize("text", [
    "sample_id,decision\nx,accept\n",
    ",".join([*LABEL_FIELDS[:-1], "reviewer"]) + "\n",
    ",".join(LABEL_FIELDS) + "\nonly,three,columns\n",
])
def test_invalid_csv_structure_writes_no_labels(dataset, tmp_path, text):
    db, version, _, _ = dataset
    csv_path = tmp_path / "malformed.csv"
    csv_path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        import_labels(db, version, csv_path)
    assert load_dataset(db, version)["labels"] == []
