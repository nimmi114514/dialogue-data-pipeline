import { useEffect, useMemo, useState } from 'react';
import { Download } from 'lucide-react';
import { getRecords, getRejected, getStats, listRuns, uploadRun } from './api';
import { ChartPanel } from './components/ChartPanel';
import { DataTables } from './components/DataTables';
import { RunHistory } from './components/RunHistory';
import { SummaryCards } from './components/SummaryCards';
import { UploadPanel } from './components/UploadPanel';
import type { CleanedRecord, RejectedRecord, Run, StatItem, Summary } from './types';

function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [topicStats, setTopicStats] = useState<StatItem[]>([]);
  const [statusStats, setStatusStats] = useState<StatItem[]>([]);
  const [ruleStats, setRuleStats] = useState<StatItem[]>([]);
  const [splitStats, setSplitStats] = useState<StatItem[]>([]);
  const [records, setRecords] = useState<CleanedRecord[]>([]);
  const [rejected, setRejected] = useState<RejectedRecord[]>([]);
  const [selected, setSelected] = useState<CleanedRecord | RejectedRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refreshRuns().catch((err: unknown) => setError(String(err)));
  }, []);

  async function refreshRuns() {
    const response = await listRuns();
    setRuns(response.items);
    if (!activeRunId && response.items[0]) {
      await loadRun(response.items[0]);
    }
  }

  async function loadRun(run: Run) {
    setActiveRunId(run.run_id);
    setSummary(run.summary);
    setSelected(null);
    const [recordsResponse, rejectedResponse, topics, statuses, rules, splits] = await Promise.all([
      getRecords(run.run_id),
      getRejected(run.run_id),
      getStats(run.run_id, 'topic'),
      getStats(run.run_id, 'status'),
      getStats(run.run_id, 'rules'),
      getStats(run.run_id, 'split'),
    ]);
    setRecords(recordsResponse.items);
    setRejected(rejectedResponse.items);
    setTopicStats(topics.items);
    setStatusStats(statuses.items);
    setRuleStats(rules.items);
    setSplitStats(splits.items);
  }

  async function handleUpload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const created = await uploadRun(file);
      const response = await listRuns();
      setRuns(response.items);
      const createdRun = response.items.find((run) => run.run_id === created.run_id);
      if (createdRun) {
        await loadRun(createdRun);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const versionLabel = useMemo(() => {
    if (!summary) return 'No dataset loaded';
    return `${summary.dataset_version.slice(0, 12)}...`;
  }, [summary]);

  return (
    <div className="app-shell">
      <RunHistory runs={runs} activeRunId={activeRunId} onSelect={(run) => void loadRun(run)} />
      <main>
        <UploadPanel busy={busy} error={error} onUpload={handleUpload} />
        <div className="version-bar">
          <span>Dataset</span>
          <strong>{versionLabel}</strong>
          {activeRunId && (
            <nav className="report-downloads" aria-label="Quality reports">
              <a href={`/api/runs/${activeRunId}/report?format=json`} download="quality_report.json">
                <Download size={16} aria-hidden="true" /> JSON report
              </a>
              <a href={`/api/runs/${activeRunId}/report?format=md`} download="quality_report.md">
                <Download size={16} aria-hidden="true" /> Markdown report
              </a>
            </nav>
          )}
        </div>
        <SummaryCards summary={summary} />
        <section className="charts-grid">
          <ChartPanel title="Disposition Status" data={statusStats} variant="pie" />
          <ChartPanel title="Split Distribution" data={splitStats} variant="pie" />
          <ChartPanel title="Topic Distribution" data={topicStats} />
          <ChartPanel title="Rule Counts" data={ruleStats} />
        </section>
        <DataTables records={records} rejected={rejected} selected={selected} onSelect={setSelected} />
      </main>
    </div>
  );
}

export default App;
