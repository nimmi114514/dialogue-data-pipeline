from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .clean import clean_record, length_issues
from .deduplicate import CandidateRecord, Disposition, resolve_duplicates
from .ingest import RejectedLine, read_jsonl
from .validate import validate_record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dialogue_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Read JSONL and validate dialogue structure.")
    check_parser.add_argument("--input", required=True, type=Path)
    check_parser.add_argument("--output", required=True, type=Path)
    check_parser.add_argument("--config", default=Path("configs/default.json"), type=Path)
    check_parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 when any data rule issue is found.",
    )

    args = parser.parse_args(argv)
    if args.command == "check":
        return run_check(args.input, args.output, args.config, args.strict)

    parser.error(f"Unsupported command: {args.command}")
    return 1


def run_check(input_path: Path, output_dir: Path, config_path: Path, strict: bool = False) -> int:
    config = _load_config(config_path)
    read_result = read_jsonl(input_path)

    candidates: list[CandidateRecord] = []
    dispositions: list[Disposition] = []
    rule_counts: dict[str, int] = {}
    cleaning_event_counts: dict[str, int] = {}

    for rejected_line in read_result.rejected:
        for reason in rejected_line.reasons:
            rule_id = reason["rule_id"]
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1
        dispositions.append(_disposition_from_rejected_line(rejected_line, "quarantined"))

    for parsed in read_result.records:
        issues = validate_record(parsed.data, config)
        if issues:
            reason_dicts = [issue.as_dict() for issue in issues]
            for issue in issues:
                rule_counts[issue.rule_id] = rule_counts.get(issue.rule_id, 0) + 1
            dispositions.append(
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
            dispositions.append(
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
    dispositions.extend(duplicate_or_conflict_dispositions)
    for disposition in duplicate_or_conflict_dispositions:
        for reason in disposition.reasons:
            rule_id = reason["rule_id"]
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1

    output_dir.mkdir(parents=True, exist_ok=True)
    cleaned_rows = [_kept_record_to_row(item.candidate) for item in kept]
    _write_jsonl(output_dir / "cleaned.jsonl", cleaned_rows)
    _write_jsonl(output_dir / "accepted.jsonl", cleaned_rows)
    _write_jsonl(
        output_dir / "rejected.jsonl",
        [_disposition_to_row(item) for item in dispositions],
    )

    duplicate_count = sum(1 for item in dispositions if item.status == "duplicate")
    quarantined_count = sum(1 for item in dispositions if item.status == "quarantined")
    summary = {
        "input_path": str(input_path),
        "config_path": str(config_path),
        "source_file_hash": read_result.source_file_hash,
        "candidate_lines": read_result.candidate_lines,
        "blank_lines": read_result.blank_lines,
        "kept_count": len(kept),
        "accepted_count": len(kept),
        "duplicate_count": duplicate_count,
        "quarantined_count": quarantined_count,
        "rejected_count": len(dispositions),
        "rule_counts": dict(sorted(rule_counts.items())),
        "cleaning_event_counts": dict(sorted(cleaning_event_counts.items())),
        "status": "completed_with_data_issues" if dispositions else "completed",
    }
    _write_json(output_dir / "summary.json", summary)

    print(
        "check completed: "
        f"kept={len(kept)} duplicate={duplicate_count} quarantined={quarantined_count} "
        f"blank_lines={read_result.blank_lines} output={output_dir}"
    )
    if strict and dispositions:
        return 2
    return 0


def _load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as file_obj:
        config = json.load(file_obj)
    if not isinstance(config, dict):
        raise ValueError("配置文件必须是 JSON 对象。")
    return config


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2, sort_keys=True)
        file_obj.write("\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file_obj.write("\n")


def _disposition_from_rejected_line(rejected_line: RejectedLine, status: str) -> Disposition:
    return Disposition(
        source_path=rejected_line.source_path,
        source_file_hash=rejected_line.source_file_hash,
        line_number=rejected_line.line_number,
        raw_text=rejected_line.raw_text,
        status=status,
        reasons=rejected_line.reasons,
    )


def _kept_record_to_row(candidate: CandidateRecord) -> dict[str, Any]:
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
        "cleaning_events": candidate.cleaning_events,
        "record": candidate.record,
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


if __name__ == "__main__":
    sys.exit(main())
