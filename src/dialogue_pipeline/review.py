from __future__ import annotations

from contextlib import closing
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import Any

from .pipeline import source_revision, stable_json_hash
from .report import build_report, write_report
from .storage import LABELS_SCHEMA, load_dataset


LABEL_FIELDS = (
    "dataset_version", "sample_id", "content_hash", "relevant", "complete",
    "decision", "reviewer", "label_origin", "notes",
)
ANNOTATION_FIELDS = LABEL_FIELDS[3:]


def labels_hash(labels: list[dict[str, Any]]) -> str:
    snapshot = [{key: row[key] for key in LABEL_FIELDS} for row in labels]
    return stable_json_hash(sorted(snapshot, key=lambda row: row["sample_id"]))


def export_template(db_path: Path, version: str, output_dir: Path) -> int:
    dataset = load_dataset(db_path, version)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "labels_template.csv").open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for row in dataset["records"]:
            writer.writerow({
                "dataset_version": version, "sample_id": row["sample_id"],
                "content_hash": row["content_hash"],
            })
    samples = [{
        "sample_id": row["sample_id"], "topic": row["topic"], "split": row.get("split"),
        "messages": json.loads(row["messages_json"]),
    } for row in dataset["records"]]
    _write_jsonl(output_dir / "review_samples.jsonl", samples)
    return len(samples)


def _validate_csv(
    input_path: Path, version: str, hashes: dict[str, str],
) -> list[dict[str, str]]:
    labels = []
    seen: set[str] = set()
    with input_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        if reader.fieldnames is None or len(reader.fieldnames) != len(LABEL_FIELDS) or set(reader.fieldnames) != set(LABEL_FIELDS):
            raise ValueError(f"CSV header must contain exactly: {', '.join(LABEL_FIELDS)}")
        for raw in reader:
            prefix = f"CSV line {reader.line_num}: "
            if None in raw or any(value is None for value in raw.values()):
                raise ValueError(prefix + "column count does not match header")
            row = {key: raw[key].strip() for key in LABEL_FIELDS}
            sample_id = row["sample_id"]
            if row["dataset_version"] != version:
                raise ValueError(prefix + "dataset_version mismatch")
            if sample_id not in hashes:
                raise ValueError(prefix + f"unknown sample_id: {sample_id}")
            if sample_id in seen:
                raise ValueError(prefix + f"duplicate label: {sample_id}")
            seen.add(sample_id)
            if row["content_hash"] != hashes[sample_id]:
                raise ValueError(prefix + f"content_hash mismatch: {sample_id}")
            if not any(row[key] for key in ANNOTATION_FIELDS):
                continue
            if row["relevant"] not in {"yes", "no", "unsure"} or row["complete"] not in {"yes", "no", "unsure"}:
                raise ValueError(prefix + "relevant/complete must be yes, no or unsure")
            if row["decision"] not in {"accept", "reject", "unsure"}:
                raise ValueError(prefix + "decision must be accept, reject or unsure")
            if not row["reviewer"] or row["label_origin"] not in {"human", "synthetic_demo"}:
                raise ValueError(prefix + "reviewer and valid label_origin are required")
            if row["decision"] == "accept" and (row["relevant"] != "yes" or row["complete"] != "yes"):
                raise ValueError(prefix + "accept requires relevant=yes and complete=yes")
            if row["decision"] != "accept" and not row["notes"]:
                raise ValueError(prefix + "reject/unsure requires notes")
            labels.append(row)
    return labels


def import_labels(db_path: Path, version: str, input_path: Path) -> int:
    uri = db_path.resolve().as_uri() + "?mode=rw"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        # Keep validation and writes in one transaction so records cannot change between them.
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM datasets WHERE dataset_version = ?", (version,)).fetchone() is None:
                raise ValueError(f"Dataset version not found: {version}")
            hashes = dict(connection.execute(
                "SELECT sample_id, content_hash FROM records WHERE dataset_version = ?", (version,),
            ))
            labels = _validate_csv(input_path, version, hashes)
            connection.execute(LABELS_SCHEMA)
            columns = ", ".join(LABEL_FIELDS)
            placeholders = ", ".join("?" for _ in LABEL_FIELDS)
            updates = ", ".join(f"{key} = excluded.{key}" for key in LABEL_FIELDS[2:])
            connection.executemany(
                f"INSERT INTO labels ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(dataset_version, sample_id) DO UPDATE SET {updates}",
                [tuple(row[key] for key in LABEL_FIELDS) for row in labels],
            )
    return len(labels)


def export_reviewed(db_path: Path, version: str, output_dir: Path) -> dict[str, Any]:
    dataset = load_dataset(db_path, version)
    summary = dataset["summary"]
    if summary.get("split_error") or any(row.get("split") not in {"train", "validation", "test"} for row in dataset["records"]):
        raise ValueError("Dataset has no complete split; add at least three independent groups and rerun.")
    hashes = {row["sample_id"]: row["content_hash"] for row in dataset["records"]}
    valid_labels = [row for row in dataset["labels"] if hashes.get(row["sample_id"]) == row["content_hash"]]
    if len(valid_labels) != len(dataset["labels"]):
        raise ValueError("Stale labels found; import labels matching the current content before export.")
    accepted = {row["sample_id"] for row in valid_labels if row["label_origin"] == "human" and row["decision"] == "accept"}
    snapshot_hash = labels_hash(valid_labels)
    export_revision = source_revision()
    review_version = stable_json_hash({
        "dataset_version": version, "labels_hash": snapshot_hash, "export_revision": export_revision,
    })
    counts = {}
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        raise ValueError("Output directory already exists; choose a new directory for this review snapshot.")
    with TemporaryDirectory(prefix=".review-", dir=output_dir.parent) as temporary:
        staging = Path(temporary) / "export"
        staging.mkdir()
        for split in ("train", "validation", "test"):
            rows = [row for row in dataset["records"] if row["sample_id"] in accepted and row["split"] == split]
            payload = [{
                "dataset_version": version, "review_version": review_version,
                "sample_id": row["sample_id"], "content_hash": row["content_hash"],
                "leakage_group_id": row["leakage_group_id"], "split": split,
                "source_file_hash": row["source_file_hash"], "line_number": row["line_number"],
                "record": json.loads(row["record_json"]),
            } for row in rows]
            _write_jsonl(staging / f"reviewed_{split}.jsonl", payload)
            counts[split] = len(rows)
            if split == "train":
                _write_jsonl(staging / "sft_train.jsonl", [{"messages": row["record"]["messages"]} for row in payload])
                _write_jsonl(staging / "sft_train.sidecar.jsonl", [{
                    "sft_line_number": index, "dataset_version": version, "review_version": review_version,
                    "sample_id": row["sample_id"], "content_hash": row["content_hash"],
                    "source_file_hash": row["source_file_hash"], "source_line_number": row["line_number"],
                } for index, row in enumerate(payload, start=1)])
        _write_jsonl(staging / "labels_snapshot.jsonl", valid_labels)
        report = build_report(summary, dataset["records"], dataset["dispositions"], dataset["config"], valid_labels)
        write_report(staging, report)
        manifest = {
            "manifest_schema_version": 1, "dataset_version": version, "review_version": review_version,
            "labels_hash": snapshot_hash, "source_file_hash": summary["source_file_hash"],
            "config_hash": summary["config_hash"], "pipeline_revision": summary["pipeline_revision"],
            "export_revision": export_revision,
            "reviewed_counts": counts, "status": "exported" if accepted else "no_human_accepted_samples",
            "output_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(staging.iterdir())},
        }
        (staging / "review_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.rename(output_dir)
    return manifest


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
