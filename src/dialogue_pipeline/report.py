from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean, median
from typing import Any

from .split import DEFAULT_SPLIT_RATIOS, SPLIT_ORDER
from .pipeline import stable_json_hash
from .storage import load_dataset


def metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def build_report(
    summary: dict[str, Any],
    records: list[dict[str, Any]],
    dispositions: list[dict[str, Any]],
    config: dict[str, Any],
    labels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize final rows without reading or modifying the raw input."""
    statuses = Counter(row["status"] for row in dispositions)
    counts = {name: statuses[name] for name in ("kept", "duplicate", "quarantined")}
    candidate_count = summary["candidate_lines"]
    kept_count = len(records)
    hashes = {row["sample_id"]: row["content_hash"] for row in records}
    valid_labels = [row for row in labels or [] if hashes.get(row["sample_id"]) == row["content_hash"]]
    human = [row for row in valid_labels if row["label_origin"] == "human"]
    human_decisions = Counter(row["decision"] for row in human)
    project = [row for row in valid_labels if row["label_origin"] == "project_review"]
    project_decisions = Counter(row["decision"] for row in project)
    demo_count = sum(row["label_origin"] == "synthetic_demo" for row in valid_labels)
    rules = Counter(reason["rule_id"] for row in dispositions for reason in row["reasons"])
    conflict_count = sum(
        any(reason["rule_id"] == "SAMPLE_ID_CONFLICT" for reason in row["reasons"])
        for row in dispositions
    )
    topics = Counter(row["topic"] for row in records)
    lengths = [row["char_count"] for row in records]
    histogram = {"0-100": 0, "101-500": 0, "501-2000": 0, "2001+": 0}
    for length in lengths:
        if length <= 100:
            bucket = "0-100"
        elif length <= 500:
            bucket = "101-500"
        elif length <= 2000:
            bucket = "501-2000"
        else:
            bucket = "2001+"
        histogram[bucket] += 1

    split_counts: Counter[str] = Counter()
    split_groups: dict[str, set[str]] = defaultdict(set)
    group_splits: dict[str, set[str]] = defaultdict(set)
    hash_splits: dict[str, set[str]] = defaultdict(set)
    for row in records:
        split = row.get("split") or "unassigned"
        split_counts[split] += 1
        group = row.get("leakage_group_id")
        if group:
            split_groups[split].add(group)
            group_splits[group].add(split)
        hash_splits[row["content_hash"]].add(split)
    group_count = len(group_splits)
    configured_ratios = config.get("split_ratios", DEFAULT_SPLIT_RATIOS)
    ratios = {
        name: float(configured_ratios.get(name, DEFAULT_SPLIT_RATIOS[name]))
        for name in SPLIT_ORDER
    }
    ratio_total = sum(ratios.values())
    splits = {
        name: {
            "records": split_counts[name],
            "groups": len(split_groups[name]),
            "record_share": metric(split_counts[name], kept_count),
            "group_share": metric(len(split_groups[name]), group_count),
            "target_share": ratios[name] / ratio_total if name in ratios and ratio_total > 0 else None,
        }
        for name in ("train", "validation", "test", "unassigned")
    }
    metrics = {
        "usable_rate": metric(kept_count, candidate_count),
        "duplicate_rate": metric(counts["duplicate"], candidate_count),
        "quarantine_rate": metric(counts["quarantined"], candidate_count),
        "human_review_coverage": metric(len(human), kept_count),
        "human_accept_rate": metric(human_decisions["accept"], len(human)),
    }
    observations = [
        {
            "name": "usable_rate", **metrics["usable_rate"],
            "meaning": "保留比例表示通过结构、清洗和去重规则的输入比例。",
            "limitation": "不能据此判断回答是否正确、有帮助或适合训练。",
        },
        {
            "name": "quarantine_rate", **metrics["quarantine_rate"],
            "meaning": "隔离比例表示需要检查原因并修复后重新提交的输入比例。",
            "limitation": "规则次数可以重叠，不能相加当作隔离行数。",
        },
        {
            "name": "duplicate_rate", **metrics["duplicate_rate"],
            "meaning": "重复比例表示规范化后因精确内容重复而移除的输入比例。",
            "limitation": "不检测语义相似改写；ID 冲突计入隔离，不计入重复。",
        },
        {
            "name": "human_review_coverage", **metrics["human_review_coverage"],
            "meaning": f"保留样本中有 {len(human)} 条带有效人工标签；{demo_count} 条演示标签不计入人工审核。",
            "limitation": "标签来源是提交者声明，系统不验证审核者身份；已审核子集的接受率不能推广到未审核数据。",
        },
    ]
    checks = {
        "candidate_accounting": candidate_count == sum(counts.values()) == len(dispositions),
        "kept_accounting": kept_count == counts["kept"] == summary["kept_count"],
        "summary_status_counts": all(counts[name] == summary[f"{name}_count"] for name in counts),
        "summary_rule_counts": dict(rules) == summary["rule_counts"],
        "valid_label_hashes": len(valid_labels) == len(labels or []),
        "split_complete": not summary.get("split_error") and split_counts["unassigned"] == 0,
        "no_group_overlap": all(len(names) == 1 for names in group_splits.values()),
        "no_content_hash_overlap": all(len(names) == 1 for names in hash_splits.values()),
    }
    return {
        "report_schema_version": 2,
        "dataset_version": summary["dataset_version"],
        "provenance": {key: summary[key] for key in ("source_file_hash", "config_hash", "pipeline_revision")},
        "status": summary["status"],
        "counts": {"candidate_lines": candidate_count, "blank_lines": summary["blank_lines"], **counts, "conflict_lines": conflict_count},
        "metrics": metrics,
        "rule_counts": dict(sorted(rules.items())),
        "cleaning_event_counts": summary["cleaning_event_counts"],
        "topic_counts": dict(sorted(topics.items())),
        "source_counts": dict(sorted(Counter(row["source"] for row in records).items())),
        "dialogue_chars": {
            "count": kept_count, "min": min(lengths) if lengths else None,
            "max": max(lengths) if lengths else None, "mean": mean(lengths) if lengths else None,
            "median": median(lengths) if lengths else None, "histogram": histogram,
        },
        "splits": splits,
        "leakage_group_count": group_count,
        "leakage_group_sizes": dict(sorted(Counter(row["leakage_group_id"] for row in records if row.get("leakage_group_id")).items())),
        "split_error": summary.get("split_error"),
        "human_review": {
            "status": "reviewed" if human else "demo_only" if demo_count else "not_imported",
            "reviewed_count": len(human), "demo_count": demo_count,
            "stale_label_count": len(labels or []) - len(valid_labels),
            "labels_hash": stable_json_hash(sorted(valid_labels, key=lambda row: row["sample_id"])),
            "decision_counts": {name: human_decisions[name] for name in ("accept", "reject", "unsure")},
        },
        "project_review": {
            "reviewed_count": len(project),
            "decision_counts": {name: project_decisions[name] for name in ("accept", "reject", "unsure")},
            "coverage": metric(len(project), kept_count),
            "accept_rate": metric(project_decisions["accept"], len(project)),
        },
        "checks": checks,
        "observations": observations,
        "limitations": [
            "主题、来源、长度和切分分布只统计最终保留样本；空白行不计入 candidate_lines。",
            "清洗事件次数来自去重前的清洗候选，包含后续重复或冲突记录；次数按实际修改数量累计。",
            "冲突行数是隔离行数的子集；规则次数可以重叠。",
            "字符数为清洗后消息文本字符总数，不是 tokenizer 的 token 数。",
            "切分只控制已声明家族和精确内容关联，不保证语义层面无泄漏；分组会使实际比例偏离目标。",
            "language=zh 是元数据校验，不是语言检测；模拟脱敏仅覆盖配置中的邮箱和手机号规则。",
        ],
    }


def load_report(db_path: Path, dataset_version: str) -> dict[str, Any]:
    dataset = load_dataset(db_path, dataset_version)
    return build_report(
        dataset["summary"], dataset["records"], dataset["dispositions"], dataset["config"], dataset["labels"],
    )


def render_markdown(report: dict[str, Any]) -> str:
    def percentage(value: float | None) -> str:
        return "N/A" if value is None else f"{value:.2%}"

    def cell(value: Any) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

    lines = ["# 对话数据质量报告", "", f"数据版本：`{report['dataset_version']}`", "", f"处理状态：{report['status']}", ""]
    if report["split_error"]:
        lines.extend([f"切分未完成：{cell(report['split_error'])}", ""])
    lines.extend(["## 输入与处置", "", "| 指标 | 数量 |", "| --- | ---: |"])
    lines.extend(f"| {name} | {value} |" for name, value in report["counts"].items())
    lines.extend(["", "## 比例与观察", ""])
    for observation in report["observations"]:
        lines.extend([
            f"- {observation['name']}：{observation['numerator']}/{observation['denominator']}（{percentage(observation['value'])}）。{observation['meaning']} 局限：{observation['limitation']}",
        ])
    acceptance = report["metrics"]["human_accept_rate"]
    lines.extend([f"- human_accept_rate：{acceptance['numerator']}/{acceptance['denominator']}（{percentage(acceptance['value'])}）；仅统计有效 human 标签。", ""])
    for key, title in (("rule_counts", "规则次数"), ("cleaning_event_counts", "清洗修改次数"), ("topic_counts", "保留样本主题分布"), ("source_counts", "保留样本来源分布")):
        lines.extend([f"## {title}", "", "| 名称 | 数量 |", "| --- | ---: |"])
        lines.extend(f"| {cell(name)} | {count} |" for name, count in report[key].items())
        if not report[key]:
            lines.append("| N/A | 0 |")
        lines.append("")
    chars = report["dialogue_chars"]
    lines.extend(["## 保留对话字符长度", "", "| 指标 | 数值 |", "| --- | ---: |"])
    lines.extend(f"| {name} | {chars[name] if chars[name] is not None else 'N/A'} |" for name in ("count", "min", "max", "mean", "median"))
    lines.extend(f"| {name} 字符 | {count} |" for name, count in chars["histogram"].items())
    lines.extend(["", "## 集合与组分布", "", "| 集合 | 样本数 | 样本占比 | 目标占比 | 组数 | 组占比 |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    lines.extend(f"| {name} | {split['records']} | {percentage(split['record_share']['value'])} | {percentage(split['target_share'])} | {split['groups']} | {percentage(split['group_share']['value'])} |" for name, split in report["splits"].items())
    lines.extend(["", f"泄漏组总数：{report['leakage_group_count']}", "", "## 一致性检查", ""])
    lines.extend(f"- {name}：{'通过' if passed else '未通过'}" for name, passed in report["checks"].items())
    review = report["human_review"]
    lines.extend([
        "", "## 人工审核", "",
        f"状态：{review['status']}；人工标签 {review['reviewed_count']} 条，演示标签 {review['demo_count']} 条，失效标签 {review['stale_label_count']} 条。未审样本不表示审核通过。",
        "", "| 决策 | 数量 |", "| --- | ---: |",
    ])
    lines.extend(f"| {name} | {count} |" for name, count in report["human_review"]["decision_counts"].items())
    project = report.get("project_review", {})
    if project.get("reviewed_count"):
        lines.extend(["", "## 样本审核", "", f"审核样本数：{project['reviewed_count']}。", "",
                      "| 决策 | 数量 |", "| --- | ---: |"])
        lines.extend(f"| {name} | {count} |" for name, count in project["decision_counts"].items())
    lines.extend(["", "## 统计口径与局限", ""])
    lines.extend(f"- {limitation}" for limitation in report["limitations"])
    lines.extend(["", "## 版本依据", ""])
    lines.extend(f"- {name}：`{value}`" for name, value in report["provenance"].items())
    return "\n".join(lines) + "\n"


def write_report(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    (output_dir / "quality_report.md").write_text(render_markdown(report), encoding="utf-8")
