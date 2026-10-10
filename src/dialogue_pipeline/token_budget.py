from __future__ import annotations

import csv
from importlib.metadata import version as package_version
import json
from pathlib import Path
from typing import Any

from .ingest import sha256_file
from .report import metric
from .storage import load_dataset


TOKENIZER_REPO = "Qwen/Qwen2.5-0.5B-Instruct"
TOKENIZER_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
TOKENIZER_FILES = ("tokenizer.json", "tokenizer_config.json", "config.json", "vocab.json", "merges.txt", "LICENSE")


def measure_tokens(
    records: list[dict[str, Any]], tokenizer: Any, budgets: list[int], output_reserve: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not budgets or any(budget < 1 for budget in budgets) or output_reserve < 0:
        raise ValueError("budgets must be positive and output_reserve must be nonnegative")
    rows = []
    for record in records:
        messages = json.loads(record["messages_json"])
        # The final assistant answer is the target, never part of the inference prompt.
        prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
        full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
        answer = tokenizer.encode(messages[-1]["content"], add_special_tokens=False)
        rows.append({
            "sample_id": record["sample_id"], "topic": record["topic"], "split": record.get("split"),
            "char_count": record["char_count"], "prompt_tokens": len(prompt),
            "sft_tokens": len(full), "answer_body_tokens": len(answer),
        })
    summary = []
    for budget in sorted(set(budgets)):
        prompt_over = sum(row["prompt_tokens"] > budget for row in rows)
        context_over = sum(row["prompt_tokens"] + output_reserve > budget for row in rows)
        sft_over = sum(row["sft_tokens"] > budget for row in rows)
        summary.append({
            "budget": budget, "sample_count": len(rows), "output_reserve": output_reserve,
            "prompt_over_count": prompt_over, "prompt_over_rate": metric(prompt_over, len(rows)),
            "context_over_count": context_over, "context_over_rate": metric(context_over, len(rows)),
            "sft_over_count": sft_over, "sft_over_rate": metric(sft_over, len(rows)),
        })
    return rows, summary


def analyze_tokens(
    db_path: Path, dataset_version: str, output_dir: Path, cache_dir: Path,
    budgets: list[int], output_reserve: int = 256,
) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer

    dataset = load_dataset(db_path, dataset_version)
    if not budgets or any(budget < 1 for budget in budgets) or output_reserve < 0:
        raise ValueError("budgets must be positive and output_reserve must be nonnegative")
    hashes = {}
    for filename in TOKENIZER_FILES:
        path = Path(hf_hub_download(TOKENIZER_REPO, filename, revision=TOKENIZER_REVISION, local_dir=cache_dir))
        hashes[filename] = sha256_file(path)
    tokenizer = AutoTokenizer.from_pretrained(cache_dir, local_files_only=True, trust_remote_code=False, use_fast=True)
    rows, summaries = measure_tokens(dataset["records"], tokenizer, budgets, output_reserve)
    report = {
        "dataset_version": dataset_version, "population": "all_kept_not_necessarily_human_reviewed",
        "tokenizer_repository": TOKENIZER_REPO, "tokenizer_revision": TOKENIZER_REVISION,
        "tokenizer_class": type(tokenizer).__name__, "tokenizer_files_sha256": hashes,
        "transformers_version": package_version("transformers"), "tokenizers_version": package_version("tokenizers"),
        "budgets": summaries,
        "longest_prompts": sorted(rows, key=lambda row: (-row["prompt_tokens"], row["sample_id"]))[:10],
        "limitations": [
            "Prompt includes the official chat template and generation marker, excludes only the final target assistant message.",
            "SFT count includes all messages and template terminators; it is not the inference input count.",
            "Context overflow assumes a fixed output reserve, not a predicted response length.",
            "Counts depend on the pinned tokenizer/template; they do not measure memory, latency, throughput or model quality.",
            "No text is truncated and no model weights or inference engine are loaded.",
            "Synthetic test fixtures cannot support real-data overflow-rate claims.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = ["sample_id", "topic", "split", "char_count", "prompt_tokens", "sft_tokens", "answer_body_tokens"]
    with (output_dir / "token_lengths.csv").open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "token_overflow.csv").open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=[*columns, "budget", "prompt_over", "context_over", "sft_over"])
        writer.writeheader()
        for budget in sorted(set(budgets)):
            for row in rows:
                flags = {
                    "prompt_over": row["prompt_tokens"] > budget,
                    "context_over": row["prompt_tokens"] + output_reserve > budget,
                    "sft_over": row["sft_tokens"] > budget,
                }
                if any(flags.values()):
                    writer.writerow({**row, "budget": budget, **flags})
    (output_dir / "token_budget.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Token 预算分析", "", f"数据版本：`{dataset_version}`", "",
        f"Tokenizer：`{TOKENIZER_REPO}@{TOKENIZER_REVISION}`；保留样本 {len(rows)} 条。", "",
        "| 预算 | 输入超限 | 输入+预留输出超限 | 完整 SFT 超限 |",
        "| --- | --- | --- | --- |",
    ]
    for summary in summaries:
        cells = []
        for key in ("prompt_over_rate", "context_over_rate", "sft_over_rate"):
            value = summary[key]
            percent = f"{value['value']:.2%}" if value["value"] is not None else "N/A"
            cells.append(f"{value['numerator']}/{value['denominator']} ({percent})")
        lines.append(f"| {summary['budget']} | " + " | ".join(cells) + " |")
    lines.extend([
        "", f"预留输出：{output_reserve} tokens。输入包含 chat template，末条 assistant 为目标答案，不放入推理输入。完整 SFT 包含答案，两个指标不可混用。", "",
        "超限明细见 token_overflow.csv，可按 sample_id 查阅原文。输入超限时先评估是否移除完整历史轮次或按任务拆分；答案/完整 SFT 超限时需另行设计样本、重新审核。这里不自动截断，也不为满足预算切断消息。", "",
        "该统计说明给定上下文预算的适配压力，不证明端侧模型能运行，更不代表内存、耗时或模型效果。", "",
        "固定版本的 tokenizer 和 chat template 与实际部署一致时，预算比较才有意义。", "",
    ])
    (output_dir / "token_budget.md").write_text("\n".join(lines), encoding="utf-8")
    return report
