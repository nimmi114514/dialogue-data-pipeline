"""Summarize reviewed subtopics and test a minimum-answer-length rule without applying it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from dialogue_pipeline.storage import load_dataset


def diagnose(db: Path, version: str, bundle_path: Path, output: Path) -> dict:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    dataset = load_dataset(db, version)
    if bundle["source_file_hash"] != dataset["summary"]["source_file_hash"]:
        raise ValueError("Review source SHA-256 mismatch")
    records = pd.DataFrame(dataset["records"])
    judgments = pd.DataFrame(bundle["labels"])
    reviewed = judgments.merge(
        records[["sample_id", "content_hash", "topic", "messages_json", "leakage_group_id"]],
        on=["sample_id", "content_hash"], validate="one_to_one",
    )
    if len(reviewed) != len(judgments):
        raise ValueError("Some judgments do not match the current records")
    imported = {row["sample_id"]: row for row in dataset["labels"]}
    for row in bundle["labels"]:
        saved = imported.get(row["sample_id"])
        if saved is None or any(saved[key] != row[key] for key in (
            "content_hash", "relevant", "complete", "decision", "reviewer", "label_origin", "notes",
        )):
            raise ValueError(f"Review judgment not imported: {row['sample_id']}")
    reviewed["answer_chars"] = reviewed["messages_json"].map(
        lambda text: len(json.loads(text)[-1]["content"])
    )
    flagged = reviewed[reviewed["answer_chars"] < 20]
    other = reviewed[reviewed["topic"] == "other"].groupby("subtopic").size().sort_index()
    summary = {
        "dataset_version": version,
        "source_file_hash": bundle["source_file_hash"],
        "reviewed_count": len(reviewed),
        "reviewed_group_count": int(reviewed["leakage_group_id"].nunique()),
        "decision_counts": reviewed["decision"].value_counts().to_dict(),
        "other_reviewed_count": int(other.sum()),
        "other_subtopics": other.to_dict(),
        "counterfactual": {
            "rule": "last assistant answer length < 20 characters",
            "applied": False,
            "flagged_count": len(flagged),
            "flagged_decisions": flagged["decision"].value_counts().to_dict(),
            "reject_total": int((reviewed["decision"] == "reject").sum()),
            "flagged_samples": flagged[["sample_id", "decision", "answer_chars", "subtopic"]].to_dict("records"),
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "review_diagnostics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    reviewed.drop(columns="messages_json").to_csv(output / "review_cases.csv", index=False)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--bundle", type=Path, default=Path("data/reviews/oasst1-review50.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.db, args.version, args.bundle, args.output), ensure_ascii=False, indent=2))
