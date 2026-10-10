from pathlib import Path

from dialogue_pipeline.clean import clean_record, content_hash
from dialogue_pipeline.deduplicate import CandidateRecord, resolve_duplicates
from dialogue_pipeline.ingest import read_jsonl
from dialogue_pipeline.validate import validate_record


CONFIG = {
    "allowed_topics": ["schedule", "study", "leisure", "explanation", "writing"],
    "allowed_language": "zh",
    "max_message_chars": 2000,
    "max_dialogue_chars": 8000,
}


def test_read_jsonl_keeps_going_after_bad_json(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.jsonl"
    input_path.write_text(
        '{"sample_id":"ok_1","group_id":"g1","source":"synthetic","topic":"study","language":"zh","messages":[{"role":"user","content":"你好"},{"role":"assistant","content":"你好。"}]}\n'
        '{"sample_id":"bad"\n'
        '\n'
        '{"sample_id":"ok_2","group_id":"g2","source":"synthetic","topic":"study","language":"zh","messages":[{"role":"user","content":"继续吗？"},{"role":"assistant","content":"继续。"}]}\n',
        encoding="utf-8",
    )

    result = read_jsonl(input_path)

    assert result.candidate_lines == 3
    assert result.blank_lines == 1
    assert len(result.records) == 2
    assert len(result.rejected) == 1
    assert result.records[1].data["sample_id"] == "ok_2"
    assert result.rejected[0].reasons[0]["rule_id"] == "JSON_PARSE_ERROR"


def test_validate_accepts_multiturn_with_optional_system() -> None:
    record = {
        "sample_id": "ok",
        "group_id": "g",
        "source": "synthetic",
        "topic": "study",
        "language": "zh",
        "messages": [
            {"role": "system", "content": "你是助手。"},
            {"role": "user", "content": "什么是 JSONL？"},
            {"role": "assistant", "content": "每行一个 JSON 对象。"},
            {"role": "user", "content": "适合流式读取吗？"},
            {"role": "assistant", "content": "适合。"},
        ],
    }

    assert validate_record(record, CONFIG) == []


def test_validate_rejects_wrong_role_order() -> None:
    record = {
        "sample_id": "bad",
        "group_id": "g",
        "source": "synthetic",
        "topic": "study",
        "language": "zh",
        "messages": [
            {"role": "assistant", "content": "先回答。"},
            {"role": "user", "content": "再提问。"},
        ],
    }

    issues = validate_record(record, CONFIG)

    assert "INVALID_ROLE_SEQUENCE" in {issue.rule_id for issue in issues}


def test_validate_rejects_type_and_empty_content() -> None:
    record = {
        "sample_id": "bad",
        "group_id": "g",
        "source": "synthetic",
        "topic": "study",
        "language": "zh",
        "messages": [
            {"role": "user", "content": 123},
            {"role": "assistant", "content": "   "},
        ],
    }

    issues = validate_record(record, CONFIG)

    assert {"INVALID_TYPE", "EMPTY_CONTENT"} <= {issue.rule_id for issue in issues}


def test_clean_record_trims_normalizes_and_redacts() -> None:
    record = {
        "sample_id": "privacy",
        "group_id": "g",
        "source": "synthetic",
        "topic": "writing",
        "language": "zh",
        "messages": [
            {
                "role": "user",
                "content": "  联系 test@example.com\r\n或 13812345678  ",
            },
            {
                "role": "assistant",
                "content": "邮箱 test@example.com，电话 13812345678。",
            },
        ],
    }

    cleaned = clean_record(record, CONFIG)

    assert cleaned.record["messages"][0]["content"] == "联系 [EMAIL]\n或 [PHONE]"
    assert cleaned.record["messages"][1]["content"] == "邮箱 [EMAIL]，电话 [PHONE]。"
    assert cleaned.char_count == sum(len(item["content"]) for item in cleaned.record["messages"])
    assert {event.event_type for event in cleaned.cleaning_events} == {
        "NORMALIZED_TEXT",
        "REDACTED_EMAIL",
        "REDACTED_PHONE",
    }


def test_content_hash_uses_normalized_messages_only() -> None:
    first = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好。"},
    ]
    second = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好。"},
    ]
    changed_metadata_record = {
        "sample_id": "different",
        "messages": second,
    }

    assert content_hash(first) == content_hash(changed_metadata_record["messages"])


def test_deduplicate_rejects_conflicting_sample_id_and_content_duplicate() -> None:
    first = _candidate("id_1", "group_a", "hash_a", 1)
    duplicate_content = _candidate("id_2", "group_b", "hash_a", 2)
    conflict_a = _candidate("conflict", "group_c", "hash_b", 3)
    conflict_b = _candidate("conflict", "group_d", "hash_c", 4)

    kept, dispositions = resolve_duplicates([first, duplicate_content, conflict_a, conflict_b])

    assert [item.candidate.record["sample_id"] for item in kept] == ["id_1"]
    assert [item.status for item in dispositions] == ["duplicate", "quarantined", "quarantined"]
    assert {item.reasons[0]["rule_id"] for item in dispositions} == {
        "DUPLICATE_CONTENT",
        "SAMPLE_ID_CONFLICT",
    }


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
