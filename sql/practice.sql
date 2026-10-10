-- Bind :dataset_version to the full version in processed/summary.json.
-- Bind :label_origin to 'project_review' for the published sample review, or 'human'.
-- Run these against the public-data practice database, not the fault-injection fixtures.

-- Review coverage and rejection ratio within the selected subset, by weak topic label.
SELECT r.topic,
       COUNT(*) AS kept_count,
       COUNT(l.sample_id) AS reviewed_count,
       SUM(CASE WHEN l.decision = 'reject' THEN 1 ELSE 0 END) AS reject_count,
       1.0 * SUM(CASE WHEN l.decision = 'reject' THEN 1 ELSE 0 END)
           / NULLIF(COUNT(l.sample_id), 0) AS reject_rate
FROM records r
LEFT JOIN labels l ON r.dataset_version = l.dataset_version
                  AND r.sample_id = l.sample_id
                  AND r.content_hash = l.content_hash
                  AND l.label_origin = :label_origin
WHERE r.dataset_version = :dataset_version
GROUP BY r.topic
ORDER BY r.topic;

-- Inspect real rejection explanations without inferring them from automatic rules.
SELECT r.sample_id, r.topic, l.reviewer, l.notes
FROM records r JOIN labels l
  ON r.dataset_version = l.dataset_version AND r.sample_id = l.sample_id
 AND r.content_hash = l.content_hash
WHERE r.dataset_version = :dataset_version
  AND l.label_origin = :label_origin AND l.decision = 'reject'
ORDER BY r.topic, r.sample_id;

-- Normalized candidate population and extra exact duplicates before resolution.
-- This is not the final duplicate disposition count: ID conflicts have separate semantics.
SELECT COUNT(content_hash) AS normalized_candidates,
       COUNT(DISTINCT content_hash) AS distinct_normalized_contents,
       COUNT(content_hash) - COUNT(DISTINCT content_hash) AS extra_exact_duplicates
FROM dispositions
WHERE dataset_version = :dataset_version;

-- Kept character lengths for comparison with the Pandas analysis.
SELECT COUNT(*) AS sample_count, AVG(char_count) AS mean_chars,
       MAX(char_count) AS max_chars
FROM records
WHERE dataset_version = :dataset_version;
