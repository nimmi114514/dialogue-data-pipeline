from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any

from .clean import content_hash
from .ingest import read_jsonl
from .pipeline import source_revision, stable_json_hash
from .report import metric


def analyze_dataset(
    input_path: Path, db_path: Path, version: str, output_dir: Path, label_origin: str = "human",
) -> dict[str, Any]:
    if label_origin not in {"human", "project_review"}:
        raise ValueError("Analysis label_origin must be human or project_review.")
    prefix = "human" if label_origin == "human" else "project"
    review_title = "人工审核" if label_origin == "human" else "样本审核"
    import pandas as pd
    from pandas.testing import assert_frame_equal

    raw = read_jsonl(input_path)
    uri = db_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("BEGIN")
        dataset = connection.execute("SELECT summary_json FROM datasets WHERE dataset_version = ?", (version,)).fetchone()
        if dataset is None:
            raise ValueError(f"Dataset version not found: {version}")
        summary = json.loads(dataset[0])
        if raw.source_file_hash != summary["source_file_hash"]:
            raise ValueError("Raw input SHA-256 differs from this dataset version")
        kept = pd.read_sql_query("SELECT sample_id, line_number, topic, char_count, content_hash FROM records WHERE dataset_version = ?", connection, params=(version,))
        dispositions = pd.read_sql_query("SELECT line_number, status, content_hash FROM dispositions WHERE dataset_version = ?", connection, params=(version,))
        if len(dispositions) != raw.candidate_lines:
            raise ValueError("Input line accounting differs from persisted dispositions")
        labels_exist = connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'labels' AND type = 'table'").fetchone()
        human_query = """
            SELECT r.sample_id, r.topic, l.decision, l.notes, l.reviewer,
                   l.relevant, l.complete, l.content_hash
            FROM records r JOIN labels l
              ON r.dataset_version = l.dataset_version AND r.sample_id = l.sample_id
             AND r.content_hash = l.content_hash
            WHERE r.dataset_version = ? AND l.label_origin = ?
        """
        human = pd.read_sql_query(human_query, connection, params=(version, label_origin)) if labels_exist else pd.DataFrame(columns=["sample_id", "topic", "decision", "notes", "reviewer", "relevant", "complete", "content_hash"])
        sql_topic = pd.read_sql_query("SELECT topic, COUNT(*) AS kept_count FROM records WHERE dataset_version = ? GROUP BY topic ORDER BY topic", connection, params=(version,))
        python_topic = kept.groupby("topic", as_index=False).size().rename(columns={"size": "kept_count"}).sort_values("topic").reset_index(drop=True)
        assert_frame_equal(python_topic, sql_topic, check_dtype=False)
        sql_status = pd.read_sql_query("SELECT status, COUNT(*) AS count FROM dispositions WHERE dataset_version = ? GROUP BY status ORDER BY status", connection, params=(version,))
        python_status = dispositions.groupby("status", as_index=False).size().rename(columns={"size": "count"}).sort_values("status").reset_index(drop=True)
        assert_frame_equal(python_status, sql_status, check_dtype=False)
        if labels_exist:
            sql_review = pd.read_sql_query(f"SELECT topic, decision, COUNT(*) AS count FROM ({human_query}) GROUP BY topic, decision ORDER BY topic, decision", connection, params=(version, label_origin))
            python_review = human.groupby(["topic", "decision"], as_index=False).size().rename(columns={"size": "count"}).sort_values(["topic", "decision"]).reset_index(drop=True)
            assert_frame_equal(python_review, sql_review, check_dtype=False)
        sql_duplicate_population = connection.execute("SELECT COUNT(content_hash), COUNT(DISTINCT content_hash) FROM dispositions WHERE dataset_version = ?", (version,)).fetchone()
        hashes = dispositions["content_hash"].dropna()
        if (len(hashes), hashes.nunique()) != sql_duplicate_population:
            raise ValueError("Pandas/SQL normalized duplicate statistics differ")
        sql_lengths = connection.execute("SELECT COUNT(*), SUM(char_count), MAX(char_count) FROM records WHERE dataset_version = ?", (version,)).fetchone()
        expected_lengths = (len(kept), int(kept["char_count"].sum()) if len(kept) else None, int(kept["char_count"].max()) if len(kept) else None)
        if expected_lengths != sql_lengths:
            raise ValueError("Pandas/SQL length statistics differ")

    parsed = {row.line_number: row.data for row in raw.records}
    before_rows = []
    for row in dispositions.itertuples(index=False):
        record = parsed.get(row.line_number)
        topic = record.get("topic") if record else None
        messages = record.get("messages") if record else None
        readable = isinstance(messages, list) and bool(messages) and all(isinstance(msg, dict) and isinstance(msg.get("content"), str) and isinstance(msg.get("role"), str) for msg in messages)
        signature = content_hash([{"role": msg["role"], "content": msg["content"]} for msg in messages]) if readable else None
        before_rows.append({
            "line_number": row.line_number,
            "topic": topic if isinstance(topic, str) and topic else "<missing_or_invalid>",
            "raw_chars": sum(len(msg["content"]) for msg in messages) if readable else None,
            "raw_hash": signature, "status": row.status, "normalized_hash": row.content_hash,
        })
    before = pd.DataFrame(before_rows, columns=["line_number", "topic", "raw_chars", "raw_hash", "status", "normalized_hash"])
    before["raw_chars"] = pd.to_numeric(before["raw_chars"], errors="coerce")
    raw_topics = before.groupby("topic").size().rename("raw_count")
    kept_topics = kept.groupby("topic").size().rename("kept_count")
    topics = pd.concat([raw_topics, kept_topics], axis=1).fillna(0).astype(int)
    topics["removed_count"] = topics["raw_count"] - topics["kept_count"]
    topics["kept_rate"] = topics["kept_count"] / topics["raw_count"].replace(0, float("nan"))
    topic_comparison = topics.reset_index().sort_values("topic")

    paired = kept.merge(before[["line_number", "raw_chars"]], on="line_number", validate="one_to_one")
    length_rows = []
    for name, values in (("raw_readable", before["raw_chars"]), ("raw_same_kept_samples", paired["raw_chars"]), ("cleaned_kept", kept["char_count"])):
        valid = values.dropna().astype(float)
        length_rows.append({
            "population": name, "count": len(valid), "missing_length": len(values) - len(valid),
            "mean": float(valid.mean()) if len(valid) else None,
            "p50": float(valid.quantile(0.5)) if len(valid) else None,
            "p95": float(valid.quantile(0.95)) if len(valid) else None,
            "max": float(valid.max()) if len(valid) else None,
        })
    length_summary = pd.DataFrame(length_rows)
    candidates = before[before["normalized_hash"].notna()]
    raw_extra = int(candidates["raw_hash"].dropna().duplicated().sum())
    normalized_extra = int(candidates["normalized_hash"].duplicated().sum())
    duplicate_summary = pd.DataFrame([
        {"stage": "raw_same_normalized_candidates", "count": len(candidates), "extra_exact_duplicates": raw_extra},
        {"stage": "normalized_before_dedup", "count": len(candidates), "extra_exact_duplicates": normalized_extra},
        {"stage": "final_kept", "count": len(kept), "extra_exact_duplicates": int(kept["content_hash"].duplicated().sum())},
    ])
    review = kept.groupby("topic").size().rename("kept_count").to_frame()
    review["reviewed_count"] = human.groupby("topic").size()
    for decision in ("accept", "reject", "unsure"):
        review[decision + "_count"] = human[human["decision"] == decision].groupby("topic").size()
    review = review.fillna(0).astype(int)
    review["coverage"] = review["reviewed_count"] / review["kept_count"]
    review["reject_rate"] = review["reject_count"] / review["reviewed_count"].replace(0, float("nan"))
    review = review.reset_index().sort_values("topic")
    rejection_notes = human[human["decision"] == "reject"].sort_values(["topic", "sample_id"])
    findings = [
        f"本次处理 {raw.candidate_lines} 条非空输入，保留 {len(kept)} 条；{review_title} {len(human)}/{len(kept)} 条。",
        f"在同一批 {len(candidates)} 条规范化候选上，原始精确重复冗余 {raw_extra} 条，规范化后 {normalized_extra} 条。该值不等于最终 duplicate 处置数，ID 冲突另计。",
    ]
    if len(human):
        ranked = review[review["reviewed_count"] > 0].sort_values(["reject_rate", "reviewed_count", "topic"], ascending=[False, False, True])
        top = ranked.iloc[0]
        findings.append(f"已审核子集中拒绝比例最高的主题为 {top['topic']}：{int(top['reject_count'])}/{int(top['reviewed_count'])}；小样本及家族相关性限制了比较，不能推广到未审核总体。具体原因见 rejection_notes.csv，不自动推断原因。")
    else:
        findings.append(f"没有匹配当前筛选条件的有效标签，{review_title}接受率与拒绝率为 N/A。")
    report = {
        "dataset_version": version, "source_file_hash": raw.source_file_hash,
        "analysis_revision": source_revision(),
        "label_origin": label_origin,
        f"{prefix}_analysis_snapshot_hash": stable_json_hash(human.sort_values("sample_id").to_dict("records")),
        "pandas_version": pd.__version__, "candidate_count": raw.candidate_lines, "kept_count": len(kept),
        f"{prefix}_review_coverage": metric(len(human), len(kept)),
        "sql_checks": {name: True for name in ("topics", "dispositions", f"{prefix}_topic_decisions", "normalized_duplicates", "kept_lengths")},
        "findings": findings,
        "limitations": [
            "故意构造的测试夹具不能用于评价公开数据质量；本报告只描述指定输入版本。",
            "公开数据主题来自适配器关键词弱标注，主题拒绝率需要结合原文和审核备注解读。",
            "raw_same_kept_samples 与 cleaned_kept 才是同样本长度比较，raw_readable 的变化还包含筛选效应。",
            "精确重复只比较角色和文本，不检测语义近似；重复统计在同一规范化候选人口上对照。",
            f"审核分母只包含版本、内容及筛选条件匹配的 {label_origin} 标签，演示标签与上游审核不计入。",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in (("topic_comparison", topic_comparison), ("length_summary", length_summary), ("duplicate_comparison", duplicate_summary), (f"{prefix}_review_by_topic", review), ("rejection_notes", rejection_notes)):
        frame.to_csv(output_dir / f"{name}.csv", index=False)
    (output_dir / "analysis.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# 数据实践分析", "", f"数据版本：`{version}`", "", *[f"- {finding}" for finding in findings], "", "## 统计口径", "", *[f"- {item}" for item in report["limitations"]], "", "## SQL 对照", "", *[f"- {name}: passed" for name in report["sql_checks"]]]
    for title, frame in (
        ("主题对照（kept_rate 为保留比例）", topic_comparison),
        ("字符长度对照", length_summary),
        ("精确重复对照", duplicate_summary),
        (f"{review_title}按主题对照（比例为 0–1，空分母为 N/A）", review),
        ("拒绝备注（最多展示前 20 条，完整记录见 CSV）", rejection_notes.head(20)),
    ):
        lines.extend(["", f"## {title}", ""])
        if frame.empty:
            lines.append("没有可展示的记录。")
            continue
        lines.extend(["| " + " | ".join(frame.columns) + " |", "| " + " | ".join("---" for _ in frame.columns) + " |"])
        for row in frame.itertuples(index=False, name=None):
            cells = []
            for value in row:
                display = "N/A" if pd.isna(value) else f"{value:.4f}" if isinstance(value, float) else str(value)
                cells.append(display.replace("&", "&amp;").replace("<", "&lt;").replace("|", "&#124;").replace("\n", " ").replace("\r", " "))
            lines.append("| " + " | ".join(cells) + " |")
    (output_dir / "analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
