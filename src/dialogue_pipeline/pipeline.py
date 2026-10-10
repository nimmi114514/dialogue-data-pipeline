from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from .clean import clean_record, length_issues
from .deduplicate import CandidateRecord, Disposition, resolve_duplicates
from .ingest import RejectedLine, read_jsonl
from .split import SplitError, assign_splits
from .validate import validate_record


@dataclass(frozen=True)
class PipelineResult:
    cleaned_rows: list[dict[str, Any]]
    rejected_rows: list[dict[str, Any]]
    disposition_rows: list[dict[str, Any]]
    split_rows: dict[str, list[dict[str, Any]]]
    summary: dict[str, Any]


def process_input(input_path: Path, config_path: Path, config: dict[str, Any]) -> PipelineResult:
    read_result = read_jsonl(input_path)
    config_hash = stable_json_hash(config)
    pipeline_revision = source_revision()
    dataset_version = stable_json_hash(
        {
            "source_file_hash": read_result.source_file_hash,
            "config_hash": config_hash,
            "pipeline_revision": pipeline_revision,
        }
    )

    candidates: list[CandidateRecord] = []
    non_kept_dispositions: list[Disposition] = []
    rule_counts: dict[str, int] = {}
    cleaning_event_counts: dict[str, int] = {}

    for rejected_line in read_result.rejected:
        for reason in rejected_line.reasons:
            rule_id = reason["rule_id"]
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1
        non_kept_dispositions.append(_disposition_from_rejected_line(rejected_line, "quarantined"))

    for parsed in read_result.records:
        issues = validate_record(parsed.data, config)
        if issues:
            reason_dicts = [issue.as_dict() for issue in issues]
            for issue in issues:
                rule_counts[issue.rule_id] = rule_counts.get(issue.rule_id, 0) + 1
            non_kept_dispositions.append(
                Disposition(
                    source_path=parsed.source_path,
                    source_file_hash=parsed.source_file_hash,
                    line_number=parsed.line_number,
                    raw_text=parsed.raw_text,
                    status="quarantined",
                    reasons=reason_dicts,
                )
            )
            continue

        cleaned = clean_record(parsed.data, config)
        post_clean_issues = length_issues(cleaned, config)
        if post_clean_issues:
            for issue in post_clean_issues:
                rule_id = issue["rule_id"]
                rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1
            non_kept_dispositions.append(
                Disposition(
                    source_path=parsed.source_path,
                    source_file_hash=parsed.source_file_hash,
                    line_number=parsed.line_number,
                    raw_text=parsed.raw_text,
                    status="quarantined",
                    reasons=post_clean_issues,
                    content_hash=cleaned.content_hash,
                )
            )
            continue

        event_dicts = [event.as_dict() for event in cleaned.cleaning_events]
        for event in cleaned.cleaning_events:
            cleaning_event_counts[event.event_type] = (
                cleaning_event_counts.get(event.event_type, 0) + event.count
            )
        candidates.append(
            CandidateRecord(
                source_path=parsed.source_path,
                source_file_hash=parsed.source_file_hash,
                line_number=parsed.line_number,
                raw_text=parsed.raw_text,
                record=cleaned.record,
                content_hash=cleaned.content_hash,
                char_count=cleaned.char_count,
                cleaning_events=event_dicts,
            )
        )

    kept, duplicate_or_conflict_dispositions = resolve_duplicates(candidates)
    non_kept_dispositions.extend(duplicate_or_conflict_dispositions)
    for disposition in duplicate_or_conflict_dispositions:
        for reason in disposition.reasons:
            rule_id = reason["rule_id"]
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1

    split_error: str | None = None
    try:
        split_result = assign_splits(kept, candidates, config)
        assignments = split_result.assignments
        split_counts = split_result.split_counts
        leakage_group_count = split_result.leakage_group_count
        leakage_group_sizes = split_result.leakage_group_sizes
    except SplitError as exc:
        split_error = str(exc)
        assignments = {}
        split_counts = {"train": 0, "validation": 0, "test": 0}
        leakage_group_count = 0
        leakage_group_sizes = {}

    cleaned_rows = [
        _kept_record_to_row(item.candidate, assignments.get(item.candidate.record["sample_id"]))
        for item in kept
    ]
    split_rows = {
        split_name: [row for row in cleaned_rows if row["split"] == split_name]
        for split_name in ("train", "validation", "test")
    }
    rejected_rows = [_disposition_to_row(item) for item in non_kept_dispositions]
    kept_disposition_rows = [_kept_disposition_to_row(row) for row in cleaned_rows]
    disposition_rows = sorted(
        kept_disposition_rows + rejected_rows,
        key=lambda row: (row["source_file_hash"], row["line_number"], row["status"]),
    )

    duplicate_count = sum(1 for item in non_kept_dispositions if item.status == "duplicate")
    quarantined_count = sum(1 for item in non_kept_dispositions if item.status == "quarantined")
    summary = {
        "dataset_version": dataset_version,
        "input_path": str(input_path),
        "config_path": str(config_path),
        "source_file_hash": read_result.source_file_hash,
        "config_hash": config_hash,
        "pipeline_revision": pipeline_revision,
        "candidate_lines": read_result.candidate_lines,
        "blank_lines": read_result.blank_lines,
        "kept_count": len(kept),
        "accepted_count": len(kept),
        "duplicate_count": duplicate_count,
        "quarantined_count": quarantined_count,
        "rejected_count": len(non_kept_dispositions),
        "rule_counts": dict(sorted(rule_counts.items())),
        "cleaning_event_counts": dict(sorted(cleaning_event_counts.items())),
        "split_counts": split_counts,
        "leakage_group_count": leakage_group_count,
        "leakage_group_sizes": dict(sorted(leakage_group_sizes.items())),
        "split_error": split_error,
        "status": "completed_with_data_issues" if non_kept_dispositions else "completed",
    }
    return PipelineResult(
        cleaned_rows=cleaned_rows,
        rejected_rows=rejected_rows,
        disposition_rows=disposition_rows,
        split_rows=split_rows,
        summary=summary,
    )


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def source_revision() -> str:
    source_root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(source_root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _disposition_from_rejected_line(rejected_line: RejectedLine, status: str) -> Disposition:
    return Disposition(
        source_path=rejected_line.source_path,
        source_file_hash=rejected_line.source_file_hash,
        line_number=rejected_line.line_number,
        raw_text=rejected_line.raw_text,
        status=status,
        reasons=rejected_line.reasons,
    )


def _kept_record_to_row(candidate: CandidateRecord, assignment: Any | None) -> dict[str, Any]:
    split = assignment.split if assignment is not None else None
    leakage_group_id = assignment.leakage_group_id if assignment is not None else None
    return {
        "source_path": candidate.source_path,
        "source_file_hash": candidate.source_file_hash,
        "line_number": candidate.line_number,
        "sample_id": candidate.record["sample_id"],
        "group_id": candidate.record["group_id"],
        "source": candidate.record["source"],
        "topic": candidate.record["topic"],
        "language": candidate.record["language"],
        "content_hash": candidate.content_hash,
        "char_count": candidate.char_count,
        "leakage_group_id": leakage_group_id,
        "split": split,
        "cleaning_events": candidate.cleaning_events,
        "record": candidate.record,
    }


def _kept_disposition_to_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": row["source_path"],
        "source_file_hash": row["source_file_hash"],
        "line_number": row["line_number"],
        "raw_text": "",
        "status": "kept",
        "reasons": [],
        "canonical_sample_id": row["sample_id"],
        "content_hash": row["content_hash"],
    }


def _disposition_to_row(disposition: Disposition) -> dict[str, Any]:
    return {
        "source_path": disposition.source_path,
        "source_file_hash": disposition.source_file_hash,
        "line_number": disposition.line_number,
        "raw_text": disposition.raw_text,
        "status": disposition.status,
        "reasons": disposition.reasons,
        "canonical_sample_id": disposition.canonical_sample_id,
        "content_hash": disposition.content_hash,
    }
