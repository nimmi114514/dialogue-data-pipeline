import type { Run } from '../types';

type Props = {
  runs: Run[];
  activeRunId: string | null;
  onSelect: (run: Run) => void;
};

export function RunHistory({ runs, activeRunId, onSelect }: Props) {
  return (
    <aside className="run-history">
      <h2>Runs</h2>
      {runs.length === 0 ? (
        <div className="empty-state">No runs yet</div>
      ) : (
        <div className="run-list">
          {runs.map((run) => (
            <button
              className={run.run_id === activeRunId ? 'run-item active' : 'run-item'}
              key={run.run_id}
              onClick={() => onSelect(run)}
            >
              <span>{run.summary.kept_count} kept</span>
              <small>{run.run_id.slice(0, 8)}</small>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
