export type Summary = {
  dataset_version: string;
  candidate_lines: number;
  blank_lines: number;
  kept_count: number;
  duplicate_count: number;
  quarantined_count: number;
  rejected_count: number;
  rule_counts: Record<string, number>;
  cleaning_event_counts: Record<string, number>;
  status: string;
};

export type Run = {
  run_id: string;
  dataset_version: string;
  started_at: string;
  finished_at: string;
  status: string;
  summary: Summary;
};

export type CreateRunResponse = {
  run_id: string;
  upload_id: string;
  dataset_version: string;
  summary: Summary;
};

export type StatItem = {
  name: string;
  value: number;
};

export type Message = {
  role: string;
  content: string;
};

export type CleanedRecord = {
  sample_id: string;
  group_id: string;
  topic: string;
  source: string;
  language: string;
  content_hash: string;
  char_count: number;
  line_number: number;
  messages: Message[];
  cleaning_events: Array<Record<string, unknown>>;
};

export type Reason = {
  rule_id: string;
  field_path: string;
  reason: string;
};

export type RejectedRecord = {
  line_number: number;
  status: string;
  reasons: Reason[];
  canonical_sample_id: string | null;
  content_hash: string | null;
  raw_text: string;
  source_path: string;
};
