from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedLine:
    source_path: str
    source_file_hash: str
    line_number: int
    raw_text: str
    data: dict[str, Any]


@dataclass(frozen=True)
class RejectedLine:
    source_path: str
    source_file_hash: str
    line_number: int
    raw_text: str
    reasons: list[dict[str, str]]


@dataclass(frozen=True)
class ReadResult:
    records: list[ParsedLine]
    rejected: list[RejectedLine]
    blank_lines: int
    candidate_lines: int
    source_file_hash: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> ReadResult:
    source_file_hash = sha256_file(path)
    records: list[ParsedLine] = []
    rejected: list[RejectedLine] = []
    blank_lines = 0
    candidate_lines = 0

    with path.open("r", encoding="utf-8") as file_obj:
        for line_number, line in enumerate(file_obj, start=1):
            raw_text = line.rstrip("\n")
            if not raw_text.strip():
                blank_lines += 1
                continue

            candidate_lines += 1
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                rejected.append(
                    RejectedLine(
                        source_path=str(path),
                        source_file_hash=source_file_hash,
                        line_number=line_number,
                        raw_text=raw_text,
                        reasons=[
                            {
                                "rule_id": "JSON_PARSE_ERROR",
                                "field_path": "$",
                                "reason": f"JSON 解析失败：{exc.msg}",
                            }
                        ],
                    )
                )
                continue

            if not isinstance(parsed, dict):
                rejected.append(
                    RejectedLine(
                        source_path=str(path),
                        source_file_hash=source_file_hash,
                        line_number=line_number,
                        raw_text=raw_text,
                        reasons=[
                            {
                                "rule_id": "INVALID_TYPE",
                                "field_path": "$",
                                "reason": "每个 JSONL 非空行必须是一个 JSON 对象。",
                            }
                        ],
                    )
                )
                continue

            records.append(
                ParsedLine(
                    source_path=str(path),
                    source_file_hash=source_file_hash,
                    line_number=line_number,
                    raw_text=raw_text,
                    data=parsed,
                )
            )

    return ReadResult(
        records=records,
        rejected=rejected,
        blank_lines=blank_lines,
        candidate_lines=candidate_lines,
        source_file_hash=source_file_hash,
    )
