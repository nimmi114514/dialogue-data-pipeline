from pathlib import Path

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
