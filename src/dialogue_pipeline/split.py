from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from .deduplicate import CandidateRecord, KeptRecord


DEFAULT_SPLIT_RATIOS = {"train": 0.8, "validation": 0.1, "test": 0.1}
SPLIT_ORDER = ("train", "validation", "test")


class SplitError(ValueError):
    pass


@dataclass(frozen=True)
class SplitAssignment:
    sample_id: str
    leakage_group_id: str
    split: str


@dataclass(frozen=True)
class SplitResult:
    assignments: dict[str, SplitAssignment]
    split_counts: dict[str, int]
    leakage_group_count: int
    leakage_group_sizes: dict[str, int]


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if right_root < left_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root


def assign_splits(
    kept_records: list[KeptRecord],
    all_candidates: list[CandidateRecord],
    config: dict[str, Any],
) -> SplitResult:
    if not kept_records:
        return SplitResult({}, {name: 0 for name in SPLIT_ORDER}, 0, {})

    leakage_group_ids = _leakage_group_ids(all_candidates)
    groups: dict[str, list[KeptRecord]] = {}
    for kept in kept_records:
        sample_id = kept.candidate.record["sample_id"]
        group_id = kept.candidate.record["group_id"]
        content_hash = kept.candidate.content_hash
        leakage_group_id = leakage_group_ids[(group_id, content_hash)]
        groups.setdefault(leakage_group_id, []).append(kept)

    if len(groups) < 3:
        raise SplitError(
            f"至少需要 3 个独立泄漏组才能划分 train/validation/test，当前只有 {len(groups)} 个。"
        )

    ratios = _split_ratios(config)
    seed = int(config.get("split_seed", 42))
    total_records = sum(len(items) for items in groups.values())
    target_counts = {name: total_records * ratios[name] for name in SPLIT_ORDER}
    split_counts = {name: 0 for name in SPLIT_ORDER}
    split_groups = {name: 0 for name in SPLIT_ORDER}
    assignments: dict[str, SplitAssignment] = {}

    ordered_groups = sorted(
        groups.items(),
        key=lambda item: (_stable_order_key(seed, item[0]), item[0]),
    )

    for split_name, (leakage_group_id, records) in zip(SPLIT_ORDER, ordered_groups[:3]):
        _assign_group(assignments, split_counts, split_groups, split_name, leakage_group_id, records)

    for leakage_group_id, records in ordered_groups[3:]:
        split_name = _choose_split(split_counts, split_groups, target_counts, len(records))
        _assign_group(assignments, split_counts, split_groups, split_name, leakage_group_id, records)

    return SplitResult(
        assignments=assignments,
        split_counts=split_counts,
        leakage_group_count=len(groups),
        leakage_group_sizes={group_id: len(records) for group_id, records in groups.items()},
    )


def _leakage_group_ids(candidates: list[CandidateRecord]) -> dict[tuple[str, str], str]:
    union_find = _UnionFind()
    for candidate in candidates:
        group_node = f"group:{candidate.record['group_id']}"
        hash_node = f"hash:{candidate.content_hash}"
        union_find.union(group_node, hash_node)

    components: dict[str, set[str]] = {}
    for candidate in candidates:
        group_node = f"group:{candidate.record['group_id']}"
        hash_node = f"hash:{candidate.content_hash}"
        root = union_find.find(group_node)
        components.setdefault(root, set()).update({group_node, hash_node})

    component_ids = {
        root: "lg_" + hashlib.sha256("|".join(sorted(nodes)).encode("utf-8")).hexdigest()[:16]
        for root, nodes in components.items()
    }

    result: dict[tuple[str, str], str] = {}
    for candidate in candidates:
        group_id = candidate.record["group_id"]
        content_hash = candidate.content_hash
        root = union_find.find(f"group:{group_id}")
        result[(group_id, content_hash)] = component_ids[root]
    return result


def _split_ratios(config: dict[str, Any]) -> dict[str, float]:
    configured = config.get("split_ratios", DEFAULT_SPLIT_RATIOS)
    ratios = {name: float(configured.get(name, DEFAULT_SPLIT_RATIOS[name])) for name in SPLIT_ORDER}
    total = sum(ratios.values())
    if total <= 0:
        raise SplitError("split_ratios 的总和必须大于 0。")
    return {name: ratios[name] / total for name in SPLIT_ORDER}


def _stable_order_key(seed: int, leakage_group_id: str) -> str:
    return hashlib.sha256(f"{seed}:{leakage_group_id}".encode("utf-8")).hexdigest()


def _assign_group(
    assignments: dict[str, SplitAssignment],
    split_counts: dict[str, int],
    split_groups: dict[str, int],
    split_name: str,
    leakage_group_id: str,
    records: list[KeptRecord],
) -> None:
    for record in records:
        sample_id = record.candidate.record["sample_id"]
        assignments[sample_id] = SplitAssignment(sample_id, leakage_group_id, split_name)
    split_counts[split_name] += len(records)
    split_groups[split_name] += 1


def _choose_split(
    split_counts: dict[str, int],
    split_groups: dict[str, int],
    target_counts: dict[str, float],
    group_size: int,
) -> str:
    def score(split_name: str) -> tuple[float, int, str]:
        after_count = split_counts[split_name] + group_size
        target = target_counts[split_name]
        return (after_count - target, split_groups[split_name], split_name)

    return min(SPLIT_ORDER, key=score)
