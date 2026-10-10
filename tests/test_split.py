from dialogue_pipeline.deduplicate import CandidateRecord, KeptRecord
from dialogue_pipeline.split import SplitError, assign_splits


def test_assign_splits_keeps_group_together_and_is_stable() -> None:
    candidates = [
        _candidate("a1", "group_a", "hash_a", 1),
        _candidate("a2", "group_a", "hash_a2", 2),
        _candidate("b1", "group_b", "hash_b", 3),
        _candidate("c1", "group_c", "hash_c", 4),
        _candidate("d1", "group_d", "hash_d", 5),
    ]
    kept = [KeptRecord(candidate) for candidate in candidates]
    config = {
        "split_seed": 123,
        "split_ratios": {"train": 0.8, "validation": 0.1, "test": 0.1},
    }

    first = assign_splits(kept, candidates, config)
    second = assign_splits(kept, candidates, config)

    assert first.assignments == second.assignments
    assert first.assignments["a1"].split == first.assignments["a2"].split
    assert sum(first.split_counts.values()) == 5
    assert all(first.split_counts[name] > 0 for name in ("train", "validation", "test"))


def test_assign_splits_links_duplicate_content_across_groups() -> None:
    candidates = [
        _candidate("a1", "group_a", "same_hash", 1),
        _candidate("b1", "group_b", "same_hash", 2),
        _candidate("c1", "group_c", "hash_c", 3),
        _candidate("d1", "group_d", "hash_d", 4),
    ]
    kept = [KeptRecord(candidate) for candidate in candidates]

    result = assign_splits(kept, candidates, {"split_seed": 42})

    assert result.assignments["a1"].leakage_group_id == result.assignments["b1"].leakage_group_id
    assert result.assignments["a1"].split == result.assignments["b1"].split


def test_assign_splits_requires_three_leakage_groups() -> None:
    candidates = [
        _candidate("a1", "group_a", "hash_a", 1),
        _candidate("b1", "group_b", "hash_b", 2),
    ]
    kept = [KeptRecord(candidate) for candidate in candidates]

    try:
        assign_splits(kept, candidates, {"split_seed": 42})
    except SplitError as exc:
        assert "至少需要 3 个独立泄漏组" in str(exc)
    else:
        raise AssertionError("Expected SplitError")


def _candidate(sample_id: str, group_id: str, record_hash: str, line_number: int) -> CandidateRecord:
    return CandidateRecord(
        source_path="sample.jsonl",
        source_file_hash="file_hash",
        line_number=line_number,
        raw_text="{}",
        record={
            "sample_id": sample_id,
            "group_id": group_id,
            "source": "synthetic",
            "topic": "study",
            "language": "zh",
            "messages": [],
        },
        content_hash=record_hash,
        char_count=0,
        cleaning_events=[],
    )
