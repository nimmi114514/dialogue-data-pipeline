import type { Run } from '../types';

type Props = {
  runs: Run[];
  activeRunId: string | null;
  onSelect: (run: Run) => void;
  busy: boolean;
  loading: boolean;
};

export function RunHistory({ runs, activeRunId, onSelect, busy, loading }: Props) {
  return (
    <aside className="run-history">
      <h2>Run history</h2>
      {runs.length === 0 ? (
        <div className="empty-state">{loading ? 'Loading...' : 'No runs yet'}</div>
      ) : (
        <div className="run-list">
          {runs.map((run) => (
            <button
              className={run.run_id === activeRunId ? 'run-item active' : 'run-item'}
              key={run.run_id}
              disabled={busy}
              aria-pressed={run.run_id === activeRunId}
              onClick={() => onSelect(run)}
            >
              <span className="run-title">{run.summary.kept_count.toLocaleString()} kept <small>{run.run_id.slice(0, 8)}</small></span>
              <time dateTime={run.started_at}>{new Date(run.started_at).toLocaleString()}</time>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
