from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_FIELDS = ("sample_id", "group_id", "source", "topic", "language", "messages")
STRING_FIELDS = ("sample_id", "group_id", "source", "topic", "language")
ALLOWED_ROLES = {"system", "user", "assistant"}


@dataclass(frozen=True)
class ValidationIssue:
    rule_id: str
    field_path: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "field_path": self.field_path,
            "reason": self.reason,
        }


def validate_record(record: dict[str, Any], config: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    allowed_topics = set(config.get("allowed_topics", []))
    allowed_language = config.get("allowed_language", "zh")

    for field in REQUIRED_FIELDS:
        if field not in record:
            issues.append(
                ValidationIssue("MISSING_FIELD", f"$.{field}", f"缺少必需字段 {field}。")
            )

    for field in STRING_FIELDS:
        if field not in record:
            continue
        value = record[field]
        if not isinstance(value, str):
            issues.append(
                ValidationIssue("INVALID_TYPE", f"$.{field}", f"{field} 必须是字符串。")
            )
        elif not value.strip():
            issues.append(
                ValidationIssue("EMPTY_CONTENT", f"$.{field}", f"{field} 清理首尾空白后不能为空。")
            )

    topic = record.get("topic")
    if isinstance(topic, str) and topic.strip() and allowed_topics and topic not in allowed_topics:
        issues.append(
            ValidationIssue("UNKNOWN_TOPIC", "$.topic", f"topic 不在配置词表中：{topic}。")
        )

    language = record.get("language")
    if isinstance(language, str) and language != allowed_language:
        issues.append(
            ValidationIssue(
                "UNSUPPORTED_LANGUAGE",
                "$.language",
                f"第一阶段只接受 language={allowed_language}。",
            )
        )

    messages = record.get("messages")
    if "messages" not in record:
        return issues
    if not isinstance(messages, list):
        issues.append(ValidationIssue("INVALID_TYPE", "$.messages", "messages 必须是数组。"))
        return issues

    if not messages:
        issues.append(ValidationIssue("MISSING_FIELD", "$.messages", "messages 至少包含 user 和 assistant。"))
        return issues

    roles: list[str] = []
    has_user = False
    has_assistant = False
    dialogue_chars = 0
    max_message_chars = int(config.get("max_message_chars", 2000))
    max_dialogue_chars = int(config.get("max_dialogue_chars", 8000))

    for index, message in enumerate(messages):
        path = f"$.messages[{index}]"
        if not isinstance(message, dict):
            issues.append(ValidationIssue("INVALID_TYPE", path, "每条 message 必须是对象。"))
            continue

        role = message.get("role")
        content = message.get("content")

        if "role" not in message:
            issues.append(ValidationIssue("MISSING_FIELD", f"{path}.role", "缺少 role。"))
        elif not isinstance(role, str):
            issues.append(ValidationIssue("INVALID_TYPE", f"{path}.role", "role 必须是字符串。"))
        elif role not in ALLOWED_ROLES:
            issues.append(
                ValidationIssue("INVALID_ROLE_SEQUENCE", f"{path}.role", f"不支持的 role：{role}。")
            )
        else:
            roles.append(role)
            has_user = has_user or role == "user"
            has_assistant = has_assistant or role == "assistant"

        if "content" not in message:
            issues.append(ValidationIssue("MISSING_FIELD", f"{path}.content", "缺少 content。"))
        elif not isinstance(content, str):
            issues.append(ValidationIssue("INVALID_TYPE", f"{path}.content", "content 必须是字符串。"))
        elif not content.strip():
            issues.append(
                ValidationIssue("EMPTY_CONTENT", f"{path}.content", "content 清理首尾空白后不能为空。")
            )
        else:
            dialogue_chars += len(content)
            if len(content) > max_message_chars:
                issues.append(
                    ValidationIssue(
                        "MESSAGE_TOO_LONG",
                        f"{path}.content",
                        f"单条消息长度 {len(content)} 超过上限 {max_message_chars}。",
                    )
                )

    if dialogue_chars > max_dialogue_chars:
        issues.append(
            ValidationIssue(
                "DIALOGUE_TOO_LONG",
                "$.messages",
                f"整段对话长度 {dialogue_chars} 超过上限 {max_dialogue_chars}。",
            )
        )

    if not has_user or not has_assistant:
        issues.append(
            ValidationIssue("INVALID_ROLE_SEQUENCE", "$.messages", "messages 至少需要一条 user 和一条 assistant。")
        )

    role_issue = _validate_role_sequence(roles)
    if role_issue is not None:
        issues.append(role_issue)

    return issues


def _validate_role_sequence(roles: list[str]) -> ValidationIssue | None:
    if not roles:
        return None

    start_index = 0
    if roles[0] == "system":
        start_index = 1
        if len(roles) == 1:
            return ValidationIssue("INVALID_ROLE_SEQUENCE", "$.messages", "system 后必须跟 user/assistant 对话。")
        if "system" in roles[1:]:
            return ValidationIssue("INVALID_ROLE_SEQUENCE", "$.messages", "system 只允许作为第一条消息。")
    elif "system" in roles:
        return ValidationIssue("INVALID_ROLE_SEQUENCE", "$.messages", "system 只允许作为第一条消息。")

    conversation_roles = roles[start_index:]
    if not conversation_roles:
        return None
    if conversation_roles[0] != "user":
        return ValidationIssue("INVALID_ROLE_SEQUENCE", "$.messages", "首条非 system 消息必须是 user。")
    if conversation_roles[-1] != "assistant":
        return ValidationIssue("INVALID_ROLE_SEQUENCE", "$.messages", "末条消息必须是 assistant。")

    for index, role in enumerate(conversation_roles):
        expected = "user" if index % 2 == 0 else "assistant"
        if role != expected:
            absolute_index = start_index + index
            return ValidationIssue(
                "INVALID_ROLE_SEQUENCE",
                f"$.messages[{absolute_index}].role",
                "第一版只支持 user/assistant 严格交替。",
            )

    return None
