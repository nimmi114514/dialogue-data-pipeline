from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .ingest import sha256_file
from .pipeline import source_revision


OASST_REPO = "OpenAssistant/oasst1"
OASST_REVISION = "fdf72ae0827c1cda404aff25b6603abec9e3399b"
OASST_FILES = {
    "train": "data/train-00000-of-00001-b42a775f407cee45.parquet",
    "validation": "data/validation-00000-of-00001-134b8fd0c89408b6.parquet",
}
TOPIC_KEYWORDS = {
    "writing": ("写作", "作文", "写一", "文案", "小说", "诗歌"),
    "schedule": ("日程", "时间表", "安排", "计划"),
    "study": ("学习", "复习", "考试", "数学", "编程", "代码", "python"),
    "leisure": ("电影", "音乐", "游戏", "旅行", "旅游"),
    "explanation": ("为什么", "为何", "什么", "如何", "解释", "区别"),
}


def classify_topic(text: str) -> str:
    lowered = text.casefold()
    return next((topic for topic, words in TOPIC_KEYWORDS.items() if any(word in lowered for word in words)), "other")


def adapt_oasst_messages(
    messages: list[dict[str, Any]], limit: int, seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Produce one complete root-to-assistant path per eligible Chinese assistant message."""
    if limit < 1:
        raise ValueError("limit must be positive")
    indexed = {}
    for message in messages:
        message_id = message["message_id"]
        if message_id in indexed:
            raise ValueError(f"Duplicate upstream message_id: {message_id}")
        indexed[message_id] = message
    candidates = []
    skipped: Counter[str] = Counter()
    for leaf in messages:
        if leaf["role"] != "assistant" or leaf["lang"] != "zh":
            continue
        chain = []
        seen = set()
        current = leaf
        error = None
        while current is not None:
            message_id = current["message_id"]
            if message_id in seen:
                error = "parent_cycle"
                break
            seen.add(message_id)
            if current["lang"] != "zh":
                error = "non_chinese_ancestor"
                break
            if current.get("deleted") or current.get("review_result") is False:
                error = "upstream_deleted_or_rejected"
                break
            chain.append(current)
            parent_id = current.get("parent_id")
            if parent_id is None:
                break
            current = indexed.get(parent_id)
            if current is None:
                error = "missing_parent"
                break
        chain.reverse()
        if not error and any(row["role"] != ("prompter" if index % 2 == 0 else "assistant") for index, row in enumerate(chain)):
            error = "invalid_role_path"
        if error:
            skipped[error] += 1
            continue
        root = chain[0]
        sample_id = "oasst1_" + leaf["message_id"]
        topic = classify_topic(root["text"]) if isinstance(root["text"], str) else "other"
        record = {
            "sample_id": sample_id, "group_id": "oasst1_" + root["message_id"],
            "source": f"{OASST_REPO}@{OASST_REVISION}", "topic": topic, "language": "zh",
            "messages": [{"role": "user" if row["role"] == "prompter" else "assistant", "content": row["text"]} for row in chain],
        }
        lineage = {
            "sample_id": sample_id, "root_message_id": root["message_id"],
            "assistant_message_id": leaf["message_id"],
            "upstream_message_ids": [row["message_id"] for row in chain],
            "upstream_split": leaf.get("upstream_split"),
            "upstream_synthetic_flags": [bool(row.get("synthetic")) for row in chain],
            "topic_method": "root_prompt_keyword_v1", "topic": topic,
        }
        candidates.append((record, lineage))
    candidates.sort(key=lambda pair: (
        hashlib.sha256(f"{seed}:{pair[0]['sample_id']}".encode()).hexdigest(), pair[0]["sample_id"],
    ))
    selected = candidates[:limit]
    counts = {
        "upstream_messages": len(messages),
        "chinese_assistant_messages": sum(row["lang"] == "zh" and row["role"] == "assistant" for row in messages),
        "eligible_paths": len(candidates), "selected_paths": len(selected),
        "selected_roots": len({record["group_id"] for record, _ in selected}),
        "skipped_paths": dict(sorted(skipped.items())),
    }
    return [record for record, _ in selected], [row for _, row in selected], counts


def import_oasst(output_dir: Path, cache_dir: Path, limit: int = 1000, seed: int = 42) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download
    import pandas as pd

    if output_dir.exists():
        raise ValueError("Output directory exists; choose a new directory to preserve provenance.")
    downloads = {}
    messages = []
    for split, filename in OASST_FILES.items():
        path = Path(hf_hub_download(OASST_REPO, filename, repo_type="dataset", revision=OASST_REVISION, local_dir=cache_dir))
        downloads[filename] = sha256_file(path)
        columns = ["message_id", "parent_id", "text", "role", "lang", "deleted", "review_result", "synthetic"]
        frame = pd.read_parquet(path, columns=columns)
        frame = frame.astype(object).where(frame.notna(), None)
        messages.extend({**row, "upstream_split": split} for row in frame.to_dict("records"))
    for filename in ("LICENSE", "README.md"):
        path = Path(hf_hub_download(OASST_REPO, filename, repo_type="dataset", revision=OASST_REVISION, local_dir=cache_dir))
        downloads[filename] = sha256_file(path)
    records, lineage, counts = adapt_oasst_messages(messages, limit, seed)
    if not records:
        raise ValueError("No eligible Chinese dialogue paths found")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".oasst-", dir=output_dir.parent) as folder:
        staging = Path(folder) / "import"
        staging.mkdir()
        for name, rows in (("dialogues.jsonl", records), ("lineage.jsonl", lineage)):
            (staging / name).write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        for filename in ("LICENSE", "README.md"):
            (staging / ("UPSTREAM_" + filename)).write_bytes((cache_dir / filename).read_bytes())
        manifest = {
            "adapter": "oasst1_root_to_assistant_v1", "adapter_revision": source_revision(),
            "repository": OASST_REPO, "revision": OASST_REVISION, "license": "Apache-2.0",
            "dataset_card": f"https://huggingface.co/datasets/{OASST_REPO}/blob/{OASST_REVISION}/README.md",
            "seed": seed, "requested_limit": limit, "counts": counts,
            "sampling": "sha256(seed:assistant_sample_id), take first limit",
            "topic_keywords": TOPIC_KEYWORDS, "topic_method": "weak_keyword_labels_not_ground_truth",
            "upstream_sha256": downloads,
            "output_sha256": {path.name: sha256_file(path) for path in sorted(staging.iterdir())},
            "limitations": [
                "Upstream ready-for-export messages are prefiltered, not raw population data.",
                "Each assistant endpoint becomes a path; related paths share a root and may overlap in history.",
                "Chinese means upstream lang=zh, not independent language detection.",
                "Original train/validation provenance is retained, but local splits are recomputed for this demonstration.",
                "Upstream review results and ranks are not this project's human labels.",
                "Adapter skips have their own denominator; pipeline rates apply only to sampled paths.",
            ],
        }
        (staging / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.rename(output_dir)
    return manifest
