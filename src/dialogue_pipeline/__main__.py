from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

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

    accepted: list[dict[str, Any]] = []
    rejected: list[RejectedLine] = list(read_result.rejected)
    rule_counts: dict[str, int] = {}

    for parsed in read_result.records:
        issues = validate_record(parsed.data, config)
        if issues:
            reason_dicts = [issue.as_dict() for issue in issues]
            for issue in issues:
                rule_counts[issue.rule_id] = rule_counts.get(issue.rule_id, 0) + 1
            rejected.append(
                RejectedLine(
                    source_path=parsed.source_path,
                    source_file_hash=parsed.source_file_hash,
                    line_number=parsed.line_number,
                    raw_text=parsed.raw_text,
                    reasons=reason_dicts,
                )
            )
        else:
            accepted.append(
                {
                    "source_path": parsed.source_path,
                    "source_file_hash": parsed.source_file_hash,
                    "line_number": parsed.line_number,
                    "record": parsed.data,
                }
            )

    for rejected_line in read_result.rejected:
        for reason in rejected_line.reasons:
            rule_id = reason["rule_id"]
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "accepted.jsonl", accepted)
    _write_jsonl(
        output_dir / "rejected.jsonl",
        [
            {
                "source_path": item.source_path,
                "source_file_hash": item.source_file_hash,
                "line_number": item.line_number,
                "raw_text": item.raw_text,
                "reasons": item.reasons,
            }
            for item in rejected
        ],
    )

    summary = {
        "input_path": str(input_path),
        "config_path": str(config_path),
        "source_file_hash": read_result.source_file_hash,
        "candidate_lines": read_result.candidate_lines,
        "blank_lines": read_result.blank_lines,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rule_counts": dict(sorted(rule_counts.items())),
        "status": "completed_with_data_issues" if rejected else "completed",
    }
    _write_json(output_dir / "summary.json", summary)

    print(
        "check completed: "
        f"accepted={len(accepted)} rejected={len(rejected)} "
        f"blank_lines={read_result.blank_lines} output={output_dir}"
    )
    if strict and rejected:
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


if __name__ == "__main__":
    sys.exit(main())
