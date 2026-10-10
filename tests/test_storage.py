import json
from pathlib import Path
import sqlite3

from dialogue_pipeline.pipeline import process_input
from dialogue_pipeline.storage import save_result


def test_save_result_is_idempotent_for_records_and_dispositions(tmp_path: Path) -> None:
    config_path = Path("configs/default.json")
    input_path = Path("data/samples/raw_dialogues.jsonl")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = process_input(input_path, config_path, config)
    db_path = tmp_path / "pipeline.sqlite"

    first_run_id = save_result(db_path, result, config)
    second_run_id = save_result(db_path, result, config)

    assert first_run_id != second_run_id

    with sqlite3.connect(db_path) as connection:
        dataset_count = connection.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        run_count = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        record_count = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        disposition_count = connection.execute("SELECT COUNT(*) FROM dispositions").fetchone()[0]

    assert dataset_count == 1
    assert run_count == 2
    assert record_count == result.summary["kept_count"]
    assert disposition_count == result.summary["candidate_lines"]


def test_sql_topic_counts_match_pipeline_summary(tmp_path: Path) -> None:
    config_path = Path("configs/default.json")
    input_path = Path("data/samples/raw_dialogues.jsonl")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = process_input(input_path, config_path, config)
    db_path = tmp_path / "pipeline.sqlite"
    save_result(db_path, result, config)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT topic, COUNT(*) AS sample_count
            FROM records
            WHERE dataset_version = ?
            GROUP BY topic
            ORDER BY topic
            """,
            (result.summary["dataset_version"],),
        ).fetchall()

    sql_total = sum(count for _, count in rows)
    python_total = result.summary["kept_count"]

    assert sql_total == python_total
    assert ("study", 3) in rows


def test_disposition_status_counts_match_summary(tmp_path: Path) -> None:
    config_path = Path("configs/default.json")
    input_path = Path("data/samples/raw_dialogues.jsonl")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    result = process_input(input_path, config_path, config)
    db_path = tmp_path / "pipeline.sqlite"
    save_result(db_path, result, config)

    with sqlite3.connect(db_path) as connection:
        rows = dict(
            connection.execute(
                """
                SELECT status, COUNT(*)
                FROM dispositions
                WHERE dataset_version = ?
                GROUP BY status
                """,
                (result.summary["dataset_version"],),
            ).fetchall()
        )

    assert rows["kept"] == result.summary["kept_count"]
    assert rows["duplicate"] == result.summary["duplicate_count"]
    assert rows["quarantined"] == result.summary["quarantined_count"]
