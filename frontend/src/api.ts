import type { CleanedRecord, CreateRunResponse, Page, RejectedRecord, Run, Source, StatItem } from './types';

export const PAGE_SIZE = 50;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function uploadRun(file: File, profile: Source['profile']): Promise<CreateRunResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('profile', profile);
  return request<CreateRunResponse>('/api/runs', {
    method: 'POST',
    body: form,
  });
}

export function listSources(signal?: AbortSignal): Promise<{ items: Source[] }> {
  return request('/api/sources', { signal });
}

export function runSource(sourceId: string): Promise<CreateRunResponse> {
  return request(`/api/sources/${sourceId}/runs`, { method: 'POST' });
}

export function listRuns(sourceId: string, signal?: AbortSignal): Promise<{ items: Run[] }> {
  return request(`/api/runs?limit=100&source_id=${encodeURIComponent(sourceId)}`, { signal });
}

export function getRecords(runId: string, page: number, signal?: AbortSignal): Promise<Page<CleanedRecord>> {
  return request(`/api/runs/${runId}/records?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`, { signal });
}

export function getRejected(runId: string, page: number, signal?: AbortSignal): Promise<Page<RejectedRecord>> {
  return request(`/api/runs/${runId}/rejected?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`, { signal });
}

export async function getStats(
  runId: string,
  kind: 'topic' | 'status' | 'rules' | 'split',
  signal?: AbortSignal,
): Promise<{ items: StatItem[] }> {
  return request<{ items: StatItem[] }>(`/api/runs/${runId}/stats/${kind}`, { signal });
}
