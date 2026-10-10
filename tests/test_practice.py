import copy
import csv
import json
from pathlib import Path
import runpy

import pytest

from dialogue_pipeline.adapters import adapt_oasst_messages
from dialogue_pipeline.analysis import analyze_dataset
from dialogue_pipeline.pipeline import process_input
from dialogue_pipeline.review import LABEL_FIELDS, export_template, import_labels
from dialogue_pipeline.storage import save_result
from dialogue_pipeline.token_budget import measure_tokens


def message(identifier, parent=None, role="prompter", language="zh", text="什么是测试？"):
    return {
        "message_id": identifier, "parent_id": parent, "role": role, "lang": language,
        "text": text, "deleted": False, "review_result": True, "synthetic": False,
        "upstream_split": "train",
    }


def test_adapter_reconstructs_multiturn_paths_and_preserves_root_groups():
    rows = [message("root"), message("a", "root", "assistant", text="测试是检查行为。"),
            message("follow", "a", text="如何执行？"), message("b", "follow", "assistant", text="运行测试。"),
            message("sibling", "root", "assistant", text="另一条回答。")]
    before = copy.deepcopy(rows)
    records, lineage, counts = adapt_oasst_messages(rows, 100, 42)
    assert rows == before
    assert len(records) == 3
    assert len({row["group_id"] for row in records}) == 1
    multi = next(row for row in records if row["sample_id"] == "oasst1_b")
    assert [row["role"] for row in multi["messages"]] == ["user", "assistant", "user", "assistant"]
    assert next(row for row in lineage if row["sample_id"] == "oasst1_b")["upstream_message_ids"] == ["root", "a", "follow", "b"]
    assert counts["eligible_paths"] == 3
    assert adapt_oasst_messages(list(reversed(rows)), 2, 42) == adapt_oasst_messages(rows, 2, 42)


def test_adapter_accounts_for_unusable_ancestry_without_inventing_conversations():
    rows = [message("missing", "absent", "assistant"),
            message("english", language="en"), message("mixed", "english", "assistant"),
            message("cycle_a", "cycle_b", "assistant"), message("cycle_b", "cycle_a"),
            message("deleted"), message("answer", "deleted", "assistant")]
    rows[-2]["deleted"] = True
    records, _, counts = adapt_oasst_messages(rows, 100, 42)
    assert records == []
    assert counts["skipped_paths"] == {
        "missing_parent": 1, "non_chinese_ancestor": 1, "parent_cycle": 1,
        "upstream_deleted_or_rejected": 1,
    }
    with pytest.raises(ValueError, match="Duplicate upstream"):
        adapt_oasst_messages([message("same"), message("same")], 10, 42)


@pytest.fixture
def practice(tmp_path):
    config_path = Path("configs/default.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    path = Path("data/samples/raw_dialogues.jsonl")
    result = process_input(path, config_path, config)
    db = tmp_path / "practice.sqlite"
    save_result(db, result, config)
    return path, db, result


def test_review_sample_is_reproducible_and_remains_unfilled(practice, tmp_path):
    _, db, result = practice
    version = result.summary["dataset_version"]
    for directory in (tmp_path / "first", tmp_path / "second"):
        assert export_template(db, version, directory, sample_size=5, seed=7) == 5
    first = tmp_path / "first"
    assert (first / "labels_template.csv").read_bytes() == (tmp_path / "second/labels_template.csv").read_bytes()
    selection = json.loads((first / "review_selection.json").read_text())
    assert selection["population_kept"] == 13
    assert selection["selected_count"] == 5
    with (first / "labels_template.csv").open(newline="") as file_obj:
        rows = list(csv.DictReader(file_obj))
    assert all(not row["decision"] and not row["label_origin"] for row in rows)
    assert {row["sample_id"] for row in rows} == set(selection["sample_ids"])
    with pytest.raises(ValueError):
        export_template(db, version, tmp_path / "bad", sample_size=0)


def test_pandas_analysis_matches_sql_and_refuses_wrong_raw_file(practice, tmp_path):
    pd = pytest.importorskip("pandas")
    path, db, result = practice
    version = result.summary["dataset_version"]
    output = tmp_path / "analysis"
    report = analyze_dataset(path, db, version, output)
    assert report["candidate_count"] == 24
    assert report["kept_count"] == 13
    assert all(report["sql_checks"].values())
    assert report["human_review_coverage"]["value"] == 0
    assert "没有匹配当前筛选条件的有效标签" in " ".join(report["findings"])
    topic = pd.read_csv(output / "topic_comparison.csv")
    assert topic["raw_count"].sum() == 24
    assert topic["kept_count"].sum() == 13
    lengths = pd.read_csv(output / "length_summary.csv").set_index("population")
    assert lengths.loc["raw_same_kept_samples", "count"] == 13
    assert lengths.loc["cleaned_kept", "count"] == 13
    wrong = tmp_path / "wrong.jsonl"
    wrong.write_text("{}\n")
    with pytest.raises(ValueError, match="SHA-256"):
        analyze_dataset(wrong, db, version, tmp_path / "wrong-output")


def test_pandas_review_questions_only_use_valid_human_labels(practice, tmp_path):
    pd = pytest.importorskip("pandas")
    path, db, result = practice
    version = result.summary["dataset_version"]
    sample = result.cleaned_rows[:2]
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for index, row in enumerate(sample):
            writer.writerow({
                "dataset_version": version, "sample_id": row["sample_id"], "content_hash": row["content_hash"],
                "relevant": "yes", "complete": "no", "decision": "reject", "reviewer": "test_fixture_only",
                "label_origin": "human" if index == 0 else "synthetic_demo", "notes": "fixture: missing requested details",
            })
    import_labels(db, version, csv_path)
    output = tmp_path / "review-analysis"
    report = analyze_dataset(path, db, version, output)
    assert report["human_review_coverage"]["numerator"] == 1
    notes = pd.read_csv(output / "rejection_notes.csv")
    assert list(notes["sample_id"]) == [sample[0]["sample_id"]]
    by_topic = pd.read_csv(output / "human_review_by_topic.csv")
    assert by_topic["reviewed_count"].sum() == 1
    assert by_topic["reject_count"].sum() == 1


def test_pandas_empty_input_has_no_nan_in_json(tmp_path):
    pytest.importorskip("pandas")
    path = tmp_path / "empty.jsonl"
    path.write_text("\n")
    config_path = Path("configs/default.json")
    config = json.loads(config_path.read_text())
    result = process_input(path, config_path, config)
    db = tmp_path / "empty.sqlite"
    save_result(db, result, config)
    output = tmp_path / "empty-analysis"
    report = analyze_dataset(path, db, result.summary["dataset_version"], output)
    assert report["human_review_coverage"]["value"] is None
    assert "NaN" not in (output / "analysis.json").read_text()


def test_token_budget_separates_prompt_target_and_context_reserve():
    calls = []

    class FixtureTokenizer:
        def apply_chat_template(self, messages, tokenize, add_generation_prompt):
            calls.append(copy.deepcopy(messages))
            assert tokenize
            return [0] * (5 if add_generation_prompt else 12)

        def encode(self, text, add_special_tokens):
            assert text == "目标回答" and not add_special_tokens
            return [0] * 4

    messages = [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "目标回答"}]
    record = {"sample_id": "fixture", "topic": "study", "split": "train", "char_count": 6, "messages_json": json.dumps(messages)}
    rows, summary = measure_tokens([record], FixtureTokenizer(), [8, 5, 8], 3)
    assert calls == [messages[:-1], messages]
    assert rows[0]["prompt_tokens"] == 5
    assert rows[0]["sft_tokens"] == 12
    assert [row["budget"] for row in summary] == [5, 8]
    assert summary[0]["prompt_over_count"] == 0
    assert summary[0]["context_over_count"] == 1
    assert summary[1]["context_over_count"] == 0
    assert summary[1]["sft_over_count"] == 1
    _, empty = measure_tokens([], FixtureTokenizer(), [512], 256)
    assert empty[0]["prompt_over_rate"]["value"] is None
    with pytest.raises(ValueError):
        measure_tokens([], FixtureTokenizer(), [0], 256)


def test_token_budget_cli_uses_real_chat_template_offline(practice, tmp_path, monkeypatch):
    transformers = pytest.importorskip("transformers")
    tokenizers = pytest.importorskip("tokenizers")
    import huggingface_hub
    from dialogue_pipeline import token_budget
    from dialogue_pipeline.__main__ import main

    cache = tmp_path / "tokenizer"
    backend = tokenizers.Tokenizer(tokenizers.models.WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer = transformers.PreTrainedTokenizerFast(
        tokenizer_object=backend, unk_token="[UNK]",
        chat_template="{% for message in messages %}{{ message['role'] }}:{{ message['content'] }};{% endfor %}{% if add_generation_prompt %}assistant:{% endif %}",
    )
    tokenizer.save_pretrained(cache)
    files = tuple(path.name for path in cache.iterdir())
    monkeypatch.setattr(token_budget, "TOKENIZER_FILES", files)

    def local_download(repo, filename, revision, local_dir):
        assert repo == token_budget.TOKENIZER_REPO
        assert revision == token_budget.TOKENIZER_REVISION
        assert local_dir == cache
        return str(cache / filename)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", local_download)
    _, db, result = practice
    output = tmp_path / "tokens"
    assert main(["token-budget", "--db", str(db), "--version", result.summary["dataset_version"],
                 "--output", str(output), "--cache", str(cache), "--budgets", "8", "16"]) == 0
    report = json.loads((output / "token_budget.json").read_text())
    assert report["budgets"][0]["sample_count"] == 13
    assert set(report["tokenizer_files_sha256"]) == set(files)


def test_project_analysis_filters_labels_and_checks_sql(practice, tmp_path):
    pd = pytest.importorskip("pandas")
    path, db, result = practice
    version = result.summary["dataset_version"]
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for row, origin in zip(result.cleaned_rows, ("human", "project_review", "synthetic_demo")):
            writer.writerow({
                "dataset_version": version, "sample_id": row["sample_id"], "content_hash": row["content_hash"],
                "relevant": "yes", "complete": "no", "decision": "reject", "reviewer": "fixture",
                "label_origin": origin, "notes": "fixture rejection",
            })
    import_labels(db, version, csv_path)
    output = tmp_path / "project-analysis"
    report = analyze_dataset(path, db, version, output, label_origin="project_review")
    assert report["project_review_coverage"]["numerator"] == 1
    assert "human_review_coverage" not in report
    assert all(report["sql_checks"].values())
    assert list(pd.read_csv(output / "rejection_notes.csv")["sample_id"]) == [result.cleaned_rows[1]["sample_id"]]
    assert pd.read_csv(output / "project_review_by_topic.csv")["reviewed_count"].sum() == 1


def test_review_diagnostics_requires_imported_matching_judgments(practice, tmp_path):
    pytest.importorskip("pandas")
    diagnose = runpy.run_path("scripts/review_diagnostics.py")["diagnose"]
    _, db, result = practice
    version = result.summary["dataset_version"]
    row = result.cleaned_rows[0]
    judgment = dict(zip(LABEL_FIELDS, (
        version, row["sample_id"], row["content_hash"], "yes", "yes",
        "accept", "fixture", "project_review", "fixture notes",
    )))
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"source_file_hash": result.summary["source_file_hash"],
                                  "labels": [{**judgment, "subtopic": "fixture"}]}))
    output = tmp_path / "diagnostics"
    with pytest.raises(ValueError, match="not imported"):
        diagnose(db, version, bundle, output)
    assert not output.exists()
    csv_path = tmp_path / "labels.csv"
    with csv_path.open("w", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerow(judgment)
    import_labels(db, version, csv_path)
    report = diagnose(db, version, bundle, output)
    assert report["reviewed_count"] == report["reviewed_group_count"] == 1
    assert report["decision_counts"] == {"accept": 1}
    assert report["counterfactual"]["applied"] is False
