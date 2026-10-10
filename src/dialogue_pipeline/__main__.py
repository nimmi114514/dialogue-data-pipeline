from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .pipeline import PipelineResult, process_input
from .storage import save_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dialogue_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Read JSONL and write file outputs.")
    _add_processing_args(check_parser)

    run_parser = subparsers.add_parser("run", help="Run processing and persist results to SQLite.")
    _add_processing_args(run_parser)
    run_parser.add_argument("--db", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "check":
        return run_check(args.input, args.output, args.config, args.strict)
    if args.command == "run":
        return run_pipeline(args.input, args.output, args.config, args.db, args.strict)

    parser.error(f"Unsupported command: {args.command}")
    return 1


def run_check(input_path: Path, output_dir: Path, config_path: Path, strict: bool = False) -> int:
    config = _load_config(config_path)
    result = process_input(input_path, config_path, config)
    _write_outputs(output_dir, result)
    _print_summary("check completed", output_dir, result)
    if strict and result.rejected_rows:
        return 2
    return 0


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    config_path: Path,
    db_path: Path,
    strict: bool = False,
) -> int:
    config = _load_config(config_path)
    result = process_input(input_path, config_path, config)
    _write_outputs(output_dir, result)
    run_id = save_result(db_path, result, config)
    _print_summary("run completed", output_dir, result, db_path=db_path, run_id=run_id)
    if strict and result.rejected_rows:
        return 2
    return 0


def _add_processing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config", default=Path("configs/default.json"), type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 2 when any data rule issue is found.",
    )


def _load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as file_obj:
        config = json.load(file_obj)
    if not isinstance(config, dict):
        raise ValueError("配置文件必须是 JSON 对象。")
    return config


def _write_outputs(output_dir: Path, result: PipelineResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_dir / "cleaned.jsonl", result.cleaned_rows)
    _write_jsonl(output_dir / "accepted.jsonl", result.cleaned_rows)
    _write_jsonl(output_dir / "rejected.jsonl", result.rejected_rows)
    for split_name, rows in result.split_rows.items():
        _write_jsonl(output_dir / f"{split_name}.jsonl", rows)
    _write_json(output_dir / "summary.json", result.summary)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2, sort_keys=True)
        file_obj.write("\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file_obj.write("\n")


def _print_summary(
    prefix: str,
    output_dir: Path,
    result: PipelineResult,
    db_path: Path | None = None,
    run_id: str | None = None,
) -> None:
    summary = result.summary
    extra = ""
    if db_path is not None:
        extra = f" db={db_path} run_id={run_id}"
    print(
        f"{prefix}: "
        f"dataset_version={summary['dataset_version']} "
        f"kept={summary['kept_count']} "
        f"duplicate={summary['duplicate_count']} "
        f"quarantined={summary['quarantined_count']} "
        f"blank_lines={summary['blank_lines']} "
        f"output={output_dir}{extra}"
    )


if __name__ == "__main__":
    sys.exit(main())
