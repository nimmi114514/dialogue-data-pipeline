import { useEffect, useState } from 'react';
import { Download, LoaderCircle } from 'lucide-react';
import { getRecords, getRejected, getStats, listRuns, listSources, runSource, uploadRun } from './api';
import { ChartPanel } from './components/ChartPanel';
import { DataTables } from './components/DataTables';
import { RunHistory } from './components/RunHistory';
import { SummaryCards } from './components/SummaryCards';
import { DatasetControls } from './components/DatasetControls';
import type { CleanedRecord, CreateRunResponse, Page, RejectedRecord, Run, Source, StatItem } from './types';

type Stats = { topic: StatItem[]; status: StatItem[]; rules: StatItem[]; split: StatItem[] };
const message = (error: unknown) => error instanceof Error ? error.message : String(error);

function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [revision, setRevision] = useState(0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [records, setRecords] = useState<Page<CleanedRecord>>({ total: 0, items: [] });
  const [rejected, setRejected] = useState<Page<RejectedRecord>>({ total: 0, items: [] });
  const [recordPage, setRecordPage] = useState(0);
  const [rejectedPage, setRejectedPage] = useState(0);
  const [selected, setSelected] = useState<CleanedRecord | RejectedRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [rejectedLoading, setRejectedLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeRun = runs.find((run) => run.run_id === activeRunId);

  useEffect(() => {
    const controller = new AbortController();
    listSources(controller.signal).then(({ items }) => {
      setSources(items);
      setSourceId(items[0]?.source_id ?? '');
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(message(err));
    }).finally(() => {
      if (!controller.signal.aborted) setCatalogLoading(false);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setRuns([]);
    setActiveRunId(null);
    setStats(null);
    setSelected(null);
    setRecordPage(0);
    setRejectedPage(0);
    if (!sourceId) return () => controller.abort();
    setHistoryLoading(true);
    listRuns(sourceId, controller.signal).then(({ items }) => {
      setRuns(items);
      setActiveRunId(items[0]?.run_id ?? null);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(message(err));
    }).finally(() => {
      if (!controller.signal.aborted) setHistoryLoading(false);
    });
    return () => controller.abort();
  }, [sourceId, revision]);

  useEffect(() => {
    const controller = new AbortController();
    setStats(null);
    if (!activeRunId) return () => controller.abort();
    Promise.all([
      getStats(activeRunId, 'topic', controller.signal),
      getStats(activeRunId, 'status', controller.signal),
      getStats(activeRunId, 'rules', controller.signal),
      getStats(activeRunId, 'split', controller.signal),
    ]).then(([topic, status, rules, split]) => {
      setStats({ topic: topic.items, status: status.items, rules: rules.items, split: split.items });
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(message(err));
    });
    return () => controller.abort();
  }, [activeRunId]);

  useEffect(() => {
    const controller = new AbortController();
    setRecords({ total: 0, items: [] });
    if (!activeRunId) return () => controller.abort();
    setRecordsLoading(true);
    getRecords(activeRunId, recordPage, controller.signal).then(setRecords).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(message(err));
    }).finally(() => {
      if (!controller.signal.aborted) setRecordsLoading(false);
    });
    return () => controller.abort();
  }, [activeRunId, recordPage]);

  useEffect(() => {
    const controller = new AbortController();
    setRejected({ total: 0, items: [] });
    if (!activeRunId) return () => controller.abort();
    setRejectedLoading(true);
    getRejected(activeRunId, rejectedPage, controller.signal).then(setRejected).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(message(err));
    }).finally(() => {
      if (!controller.signal.aborted) setRejectedLoading(false);
    });
    return () => controller.abort();
  }, [activeRunId, rejectedPage]);

  function selectSource(id: string) {
    if (id === sourceId) return;
    setError(null);
    setActiveRunId(null);
    setSourceId(id);
  }

  function selectRun(run: Run) {
    setError(null);
    setSelected(null);
    setRecordPage(0);
    setRejectedPage(0);
    setActiveRunId(run.run_id);
  }

  async function process(action: () => Promise<CreateRunResponse>) {
    setBusy(true);
    setError(null);
    try {
      const created = await action();
      const { items } = await listSources();
      setSources(items);
      setSourceId(created.source_id);
      setRevision((value) => value + 1);
    } catch (err) {
      setError(message(err));
      // A saved upload remains selectable even when processing fails.
      listSources().then(({ items }) => setSources(items)).catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <RunHistory runs={runs} activeRunId={activeRunId} onSelect={selectRun} busy={busy} loading={historyLoading} />
      <main>
        <DatasetControls sources={sources} selectedId={sourceId} busy={busy} loading={catalogLoading}
          onSelect={selectSource} onRun={() => void process(() => runSource(sourceId))}
          onUpload={(file, profile) => void process(() => uploadRun(file, profile))} />
        {error && <div className="error" role="alert">{error}</div>}
        {activeRun ? (
          <>
            <div className="version-bar">
              <span>Version</span>
              <strong title={activeRun.dataset_version}>{activeRun.dataset_version.slice(0, 12)}...</strong>
              <nav className="report-downloads" aria-label="Quality reports">
                <a href={`/api/runs/${activeRunId}/report?format=json`} download="quality_report.json">
                  <Download size={16} aria-hidden="true" /> JSON report
                </a>
                <a href={`/api/runs/${activeRunId}/report?format=md`} download="quality_report.md">
                  <Download size={16} aria-hidden="true" /> Markdown report
                </a>
              </nav>
            </div>
            <SummaryCards summary={activeRun.summary} />
            {stats ? (
              <section className="charts-grid">
                <ChartPanel title="Disposition Status" data={stats.status} variant="pie" />
                <ChartPanel title="Split Distribution" data={stats.split} variant="pie" />
                <ChartPanel title="Topic Distribution" data={stats.topic} />
                <ChartPanel title="Rule Counts" data={stats.rules} />
              </section>
            ) : <div className="empty-state" role="status"><LoaderCircle className="spin" size={20} /> Loading results...</div>}
            <DataTables records={records} rejected={rejected} selected={selected} onSelect={setSelected}
              recordPage={recordPage} rejectedPage={rejectedPage}
              recordsLoading={recordsLoading} rejectedLoading={rejectedLoading}
              onRecordPage={(page) => { setSelected(null); setRecordPage(page); }}
              onRejectedPage={(page) => { setSelected(null); setRejectedPage(page); }} />
          </>
        ) : (
          <div className="workspace-empty" role="status">
            {historyLoading || catalogLoading ? 'Loading...' : sourceId ? 'No processing runs' : 'No datasets'}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
