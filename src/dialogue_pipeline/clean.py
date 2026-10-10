from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any


DEFAULT_EMAIL_PATTERN = r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
DEFAULT_PHONE_PATTERN = r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?!\d)"


@dataclass(frozen=True)
class CleaningEvent:
    event_type: str
    field_path: str
    count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "field_path": self.field_path,
            "count": self.count,
        }


@dataclass(frozen=True)
class CleanedRecord:
    record: dict[str, Any]
    content_hash: str
    char_count: int
    cleaning_events: list[CleaningEvent]


def clean_record(record: dict[str, Any], config: dict[str, Any]) -> CleanedRecord:
    cleaned: dict[str, Any] = {
        "sample_id": _normalize_metadata_text(record["sample_id"]),
        "group_id": _normalize_metadata_text(record["group_id"]),
        "source": _normalize_metadata_text(record["source"]),
        "topic": _normalize_metadata_text(record["topic"]),
        "language": _normalize_metadata_text(record["language"]),
        "messages": [],
    }
    events: list[CleaningEvent] = []
    char_count = 0

    for index, message in enumerate(record["messages"]):
        role = message["role"]
        original_content = message["content"]
        field_path = f"$.messages[{index}].content"
        content = _normalize_message_text(original_content)
        if content != original_content:
            events.append(CleaningEvent("NORMALIZED_TEXT", field_path, 1))

        content, email_count = _redact(
            content,
            config.get("email_pattern", DEFAULT_EMAIL_PATTERN),
            "[EMAIL]",
        )
        if email_count:
            events.append(CleaningEvent("REDACTED_EMAIL", field_path, email_count))

        content, phone_count = _redact(
            content,
            config.get("phone_pattern", DEFAULT_PHONE_PATTERN),
            "[PHONE]",
        )
        if phone_count:
            events.append(CleaningEvent("REDACTED_PHONE", field_path, phone_count))

        char_count += len(content)
        cleaned["messages"].append({"role": role, "content": content})

    return CleanedRecord(
        record=cleaned,
        content_hash=content_hash(cleaned["messages"]),
        char_count=char_count,
        cleaning_events=events,
    )


def length_issues(cleaned: CleanedRecord, config: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    max_message_chars = int(config.get("max_message_chars", 2000))
    max_dialogue_chars = int(config.get("max_dialogue_chars", 8000))

    for index, message in enumerate(cleaned.record["messages"]):
        content_len = len(message["content"])
        if content_len > max_message_chars:
            issues.append(
                {
                    "rule_id": "MESSAGE_TOO_LONG",
                    "field_path": f"$.messages[{index}].content",
                    "reason": f"单条消息长度 {content_len} 超过上限 {max_message_chars}。",
                }
            )

    if cleaned.char_count > max_dialogue_chars:
        issues.append(
            {
                "rule_id": "DIALOGUE_TOO_LONG",
                "field_path": "$.messages",
                "reason": f"整段对话长度 {cleaned.char_count} 超过上限 {max_dialogue_chars}。",
            }
        )

    return issues


def content_hash(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_metadata_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


def _normalize_message_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.strip()


def _redact(value: str, pattern: str, replacement: str) -> tuple[str, int]:
    return re.subn(pattern, replacement, value)
