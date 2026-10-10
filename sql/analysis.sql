-- Replace :dataset_version with the dataset version from artifacts/.../summary.json.

-- Dataset-level summary.
SELECT
  dataset_version,
  status,
  json_extract(summary_json, '$.candidate_lines') AS candidate_lines,
  json_extract(summary_json, '$.kept_count') AS kept_count,
  json_extract(summary_json, '$.duplicate_count') AS duplicate_count,
  json_extract(summary_json, '$.quarantined_count') AS quarantined_count,
  json_extract(summary_json, '$.leakage_group_count') AS leakage_group_count
FROM datasets
WHERE dataset_version = :dataset_version;

-- Kept sample count by topic.
SELECT
  topic,
  COUNT(*) AS sample_count
FROM records
WHERE dataset_version = :dataset_version
GROUP BY topic
ORDER BY sample_count DESC, topic ASC;

-- Source distribution for kept records.
SELECT
  source,
  COUNT(*) AS sample_count
FROM records
WHERE dataset_version = :dataset_version
GROUP BY source
ORDER BY sample_count DESC, source ASC;

-- Train / validation / test distribution for kept records.
SELECT
  COALESCE(split, 'unassigned') AS split,
  COUNT(*) AS sample_count,
  COUNT(DISTINCT leakage_group_id) AS leakage_group_count
FROM records
WHERE dataset_version = :dataset_version
GROUP BY split
ORDER BY sample_count DESC, split ASC;

-- Topic distribution within each split.
SELECT
  COALESCE(split, 'unassigned') AS split,
  topic,
  COUNT(*) AS sample_count
FROM records
WHERE dataset_version = :dataset_version
GROUP BY split, topic
ORDER BY split ASC, sample_count DESC, topic ASC;

-- Final disposition status counts for every non-empty input line.
SELECT
  status,
  COUNT(*) AS line_count
FROM dispositions
WHERE dataset_version = :dataset_version
GROUP BY status
ORDER BY line_count DESC, status ASC;

-- Rule occurrence counts. Requires SQLite JSON functions.
SELECT
  json_extract(reason.value, '$.rule_id') AS rule_id,
  COUNT(*) AS occurrence_count
FROM dispositions
JOIN json_each(dispositions.reasons_json) AS reason
WHERE dataset_version = :dataset_version
  AND json_extract(reason.value, '$.rule_id') IS NOT NULL
GROUP BY rule_id
ORDER BY occurrence_count DESC, rule_id ASC;

-- Recent runs for this dataset version.
SELECT
  run_id,
  started_at,
  finished_at,
  status
FROM runs
WHERE dataset_version = :dataset_version
ORDER BY started_at DESC;
