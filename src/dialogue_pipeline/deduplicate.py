from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateRecord:
    source_path: str
    source_file_hash: str
    line_number: int
    raw_text: str
    record: dict[str, Any]
    content_hash: str
    char_count: int
    cleaning_events: list[dict[str, Any]]


@dataclass(frozen=True)
class KeptRecord:
    candidate: CandidateRecord


@dataclass(frozen=True)
class Disposition:
    source_path: str
    source_file_hash: str
    line_number: int
    raw_text: str
    status: str
    reasons: list[dict[str, str]]
    canonical_sample_id: str | None = None
    content_hash: str | None = None


def resolve_duplicates(candidates: list[CandidateRecord]) -> tuple[list[KeptRecord], list[Disposition]]:
    conflict_ids = _find_conflict_sample_ids(candidates)
    kept: list[KeptRecord] = []
    dispositions: list[Disposition] = []
    seen_content: dict[str, CandidateRecord] = {}

    for candidate in candidates:
        sample_id = candidate.record["sample_id"]
        if sample_id in conflict_ids:
            dispositions.append(
                Disposition(
                    source_path=candidate.source_path,
                    source_file_hash=candidate.source_file_hash,
                    line_number=candidate.line_number,
                    raw_text=candidate.raw_text,
                    status="quarantined",
                    reasons=[
                        {
                            "rule_id": "SAMPLE_ID_CONFLICT",
                            "field_path": "$.sample_id",
                            "reason": f"sample_id={sample_id} 对应多个不同规范化内容，全部隔离。",
                        }
                    ],
                    content_hash=candidate.content_hash,
                )
            )
            continue

        canonical = seen_content.get(candidate.content_hash)
        if canonical is not None:
            dispositions.append(
                Disposition(
                    source_path=candidate.source_path,
                    source_file_hash=candidate.source_file_hash,
                    line_number=candidate.line_number,
                    raw_text=candidate.raw_text,
                    status="duplicate",
                    reasons=[
                        {
                            "rule_id": "DUPLICATE_CONTENT",
                            "field_path": "$.messages",
                            "reason": (
                                "规范化和脱敏后的对话内容与已保留记录重复，"
                                f"保留 sample_id={canonical.record['sample_id']}。"
                            ),
                        }
                    ],
                    canonical_sample_id=canonical.record["sample_id"],
                    content_hash=candidate.content_hash,
                )
            )
            continue

        seen_content[candidate.content_hash] = candidate
        kept.append(KeptRecord(candidate))

    return kept, dispositions


def _find_conflict_sample_ids(candidates: list[CandidateRecord]) -> set[str]:
    hashes_by_sample_id: dict[str, set[str]] = {}
    for candidate in candidates:
        sample_id = candidate.record["sample_id"]
        hashes_by_sample_id.setdefault(sample_id, set()).add(candidate.content_hash)
    return {
        sample_id
        for sample_id, content_hashes in hashes_by_sample_id.items()
        if len(content_hashes) > 1
    }
