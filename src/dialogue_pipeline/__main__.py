from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from .pipeline import PipelineResult, process_input
from .export import write_outputs
from .report import load_report, write_report
from .review import export_reviewed, export_template, import_labels
from .storage import save_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dialogue_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Read JSONL and write file outputs.")
    _add_processing_args(check_parser)

    run_parser = subparsers.add_parser("run", help="Run processing and persist results to SQLite.")
    _add_processing_args(run_parser)
    run_parser.add_argument("--db", required=True, type=Path)

    report_parser = subparsers.add_parser("report", help="Report an existing SQLite dataset without reprocessing.")
    report_parser.add_argument("--db", required=True, type=Path)
    report_parser.add_argument("--version", required=True)
    report_parser.add_argument("--output", required=True, type=Path)

    for command, help_text in (
        ("labels-template", "Export an empty review CSV and dialogue context."),
        ("labels-import", "Validate and atomically import review labels."),
        ("export-reviewed", "Export human-accepted splits and training messages."),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--db", required=True, type=Path)
        command_parser.add_argument("--version", required=True)
        argument = "--input" if command == "labels-import" else "--output"
        command_parser.add_argument(argument, required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "check":
        return run_check(args.input, args.output, args.config, args.strict)
    if args.command == "run":
        return run_pipeline(args.input, args.output, args.config, args.db, args.strict)
    if args.command == "report":
        try:
            report = load_report(args.db, args.version)
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"report failed: {exc}", file=sys.stderr)
            return 1
        write_report(args.output, report)
        print(f"report completed: dataset_version={args.version} output={args.output}")
        return 0
    if args.command in {"labels-template", "labels-import", "export-reviewed"}:
        try:
            if args.command == "labels-template":
                count = export_template(args.db, args.version, args.output)
                print(f"labels template exported: samples={count} output={args.output}")
            elif args.command == "labels-import":
                count = import_labels(args.db, args.version, args.input)
                print(f"labels imported: count={count} dataset_version={args.version}")
            else:
                manifest = export_reviewed(args.db, args.version, args.output)
                print(f"reviewed export completed: review_version={manifest['review_version']} counts={manifest['reviewed_counts']} output={args.output}")
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 1


def run_check(input_path: Path, output_dir: Path, config_path: Path, strict: bool = False) -> int:
    config = _load_config(config_path)
    result = process_input(input_path, config_path, config)
    write_outputs(output_dir, result, config)
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
    run_id = save_result(db_path, result, config)
    write_outputs(output_dir, result, config, report=load_report(db_path, result.summary["dataset_version"]))
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
