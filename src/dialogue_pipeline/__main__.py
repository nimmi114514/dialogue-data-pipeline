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
from .review import export_reviewed, export_template, import_labels, replay_labels
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

    catalog_parser = subparsers.add_parser("catalog-add", help="Store a raw JSONL dataset for dashboard runs.")
    catalog_parser.add_argument("--input", required=True, type=Path)
    catalog_parser.add_argument("--db", type=Path, default=Path("artifacts/web/dashboard.sqlite"))
    catalog_parser.add_argument("--name")
    catalog_parser.add_argument("--profile", choices=("default", "oasst1"), default="default")
    catalog_parser.add_argument("--origin", choices=("local", "public"), default="local")

    for command, help_text in (
        ("labels-template", "Export an empty review CSV and dialogue context."),
        ("labels-import", "Validate and atomically import review labels."),
        ("export-reviewed", "Export accepted splits and training messages."),
        ("labels-replay", "Bind published review judgments to matching data."),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--db", required=True, type=Path)
        command_parser.add_argument("--version", required=True)
        argument = "--input" if command in {"labels-import", "labels-replay"} else "--output"
        command_parser.add_argument(argument, required=True, type=Path)
        if command == "labels-replay":
            command_parser.add_argument("--output", required=True, type=Path)
        if command == "labels-template":
            command_parser.add_argument("--sample-size", type=int)
            command_parser.add_argument("--seed", type=int, default=42)
        if command == "export-reviewed":
            command_parser.add_argument("--label-origin", choices=("human", "project_review"), default="human")

    source_parser = subparsers.add_parser("import-oasst", help="Download pinned OASST1 and sample Chinese dialogue paths.")
    source_parser.add_argument("--output", required=True, type=Path)
    source_parser.add_argument("--cache", type=Path, default=Path("artifacts/external/oasst1"))
    source_parser.add_argument("--limit", type=int, default=1000)
    source_parser.add_argument("--seed", type=int, default=42)
    for command in ("analyze", "token-budget"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--db", required=True, type=Path)
        command_parser.add_argument("--version", required=True)
        command_parser.add_argument("--output", required=True, type=Path)
        if command == "analyze":
            command_parser.add_argument("--input", required=True, type=Path)
            command_parser.add_argument("--label-origin", choices=("human", "project_review"), default="human")
        else:
            command_parser.add_argument("--cache", type=Path, default=Path("artifacts/external/qwen2.5-0.5b-tokenizer"))
            command_parser.add_argument("--budgets", nargs="+", type=int, default=[512, 1024, 2048, 4096])
            command_parser.add_argument("--output-reserve", type=int, default=256)

    args = parser.parse_args(argv)
    if args.command == "catalog-add":
        from .catalog import MAX_SOURCE_BYTES, register_source
        try:
            with args.input.open("rb") as file_obj:
                content = file_obj.read(MAX_SOURCE_BYTES + 1)
            source = register_source(args.db, content, args.input.name, args.profile, args.name, args.origin)
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"catalog-add failed: {exc}", file=sys.stderr)
            return 1
        print(f"catalog source saved: source_id={source['source_id']} rows={source['row_count']} profile={source['profile']}")
        return 0
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
    if args.command in {"labels-template", "labels-import", "export-reviewed", "labels-replay"}:
        try:
            if args.command == "labels-template":
                count = export_template(args.db, args.version, args.output, args.sample_size, args.seed)
                print(f"labels template exported: samples={count} output={args.output}")
            elif args.command == "labels-import":
                count = import_labels(args.db, args.version, args.input)
                print(f"labels imported: count={count} dataset_version={args.version}")
            elif args.command == "labels-replay":
                count = replay_labels(args.db, args.version, args.input, args.output)
                print(f"labels bound: count={count} output={args.output}")
            else:
                manifest = export_reviewed(args.db, args.version, args.output, args.label_origin)
                print(f"reviewed export completed: review_version={manifest['review_version']} counts={manifest['reviewed_counts']} output={args.output}")
        except (ValueError, OSError, sqlite3.Error) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command in {"import-oasst", "analyze", "token-budget"}:
        try:
            if args.command == "import-oasst":
                from .adapters import import_oasst
                result = import_oasst(args.output, args.cache, args.limit, args.seed)
                print(f"OASST import completed: {result['counts']} output={args.output}")
            elif args.command == "analyze":
                from .analysis import analyze_dataset
                result = analyze_dataset(args.input, args.db, args.version, args.output, args.label_origin)
                print(f"Pandas/SQL analysis completed: kept={result['kept_count']} output={args.output}")
            else:
                from .token_budget import analyze_tokens
                result = analyze_tokens(args.db, args.version, args.output, args.cache, args.budgets, args.output_reserve)
                print(f"Token budget analysis completed: tokenizer={result['tokenizer_revision']} output={args.output}")
        except ImportError as exc:
            print(f"{args.command} failed: install optional dependencies with pip install -e '.[analysis]': {exc}", file=sys.stderr)
            return 1
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
    _print_summary("check split failed" if result.summary["split_error"] else "check completed", output_dir, result)
    if result.summary["split_error"]:
        print(result.summary["split_error"], file=sys.stderr)
        return 3
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
    _print_summary("run split failed" if result.summary["split_error"] else "run completed", output_dir, result, db_path=db_path, run_id=run_id)
    if result.summary["split_error"]:
        print(result.summary["split_error"], file=sys.stderr)
        return 3
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
        help="Return exit code 2 for data rule issues; split failure always returns 3.",
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
