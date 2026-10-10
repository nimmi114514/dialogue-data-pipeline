import type { CleanedRecord, CreateRunResponse, RejectedRecord, Run, StatItem } from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function uploadRun(file: File): Promise<CreateRunResponse> {
  const form = new FormData();
  form.append('file', file);
  return request<CreateRunResponse>('/api/runs', {
    method: 'POST',
    body: form,
  });
}

export async function listRuns(): Promise<{ items: Run[] }> {
  return request<{ items: Run[] }>('/api/runs');
}

export async function getRecords(runId: string): Promise<{ total: number; items: CleanedRecord[] }> {
  return request<{ total: number; items: CleanedRecord[] }>(`/api/runs/${runId}/records?limit=200`);
}

export async function getRejected(runId: string): Promise<{ total: number; items: RejectedRecord[] }> {
  return request<{ total: number; items: RejectedRecord[] }>(`/api/runs/${runId}/rejected?limit=200`);
}

export async function getStats(
  runId: string,
  kind: 'topic' | 'status' | 'rules' | 'split',
): Promise<{ items: StatItem[] }> {
  return request<{ items: StatItem[] }>(`/api/runs/${runId}/stats/${kind}`);
}
