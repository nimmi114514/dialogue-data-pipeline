from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pipeline import PipelineResult
from .report import build_report, write_report


def write_outputs(
    output_dir: Path, result: PipelineResult, config: dict[str, Any],
    report: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "cleaned": result.cleaned_rows,
        "accepted": result.cleaned_rows,
        "rejected": result.rejected_rows,
        **result.split_rows,
    }
    for name, rows in files.items():
        with (output_dir / f"{name}.jsonl").open("w", encoding="utf-8") as file_obj:
            for row in rows:
                file_obj.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (output_dir / "summary.json").write_text(
        json.dumps(result.summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    write_report(output_dir, report if report is not None else build_report(
        result.summary, result.cleaned_rows, result.disposition_rows, config,
    ))
