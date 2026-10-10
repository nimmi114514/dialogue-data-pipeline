import { Download, LoaderCircle, Play, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import type { Source } from '../types';

type Props = {
  sources: Source[];
  selectedId: string;
  busy: boolean;
  loading: boolean;
  onSelect: (id: string) => void;
  onRun: () => void;
  onUpload: (file: File, profile: Source['profile']) => void;
};

export function DatasetControls({ sources, selectedId, busy, loading, onSelect, onRun, onUpload }: Props) {
  const [profile, setProfile] = useState<Source['profile']>('default');
  const fileInput = useRef<HTMLInputElement>(null);
  const source = sources.find((item) => item.source_id === selectedId);

  return (
    <header className="dataset-controls">
      <div className="workspace-heading">
        <h1>Dialogue Data Pipeline</h1>
        <span className="workspace-label">Data workspace</span>
      </div>
      <div className="dataset-toolbar">
        <label className="dataset-picker">
          <span>Dataset</span>
          <select aria-label="Dataset" value={selectedId} disabled={busy || loading} onChange={(event) => onSelect(event.target.value)}>
            <option value="" disabled>{loading ? 'Loading datasets...' : 'Select a dataset'}</option>
            {sources.map((item) => (
              <option key={item.source_id} value={item.source_id}>{item.name} · {item.row_count.toLocaleString()} rows · {item.profile} · {item.content_sha256.slice(0, 6)}</option>
            ))}
          </select>
        </label>
        <button className="primary-button" disabled={busy || loading || !source} onClick={onRun}>
          {busy ? <LoaderCircle size={17} className="spin" /> : <Play size={17} />}
          {busy ? 'Processing...' : 'Run dataset'}
        </button>
        <div className="upload-actions">
          <label>
            <span>Upload profile</span>
            <select aria-label="Upload profile" value={profile} disabled={busy || loading} onChange={(event) => setProfile(event.target.value as Source['profile'])}>
              <option value="default">Standard</option>
              <option value="oasst1">OASST1 · includes other</option>
            </select>
          </label>
          <button className="secondary-button" disabled={busy || loading} onClick={() => fileInput.current?.click()}>
            <Upload size={17} /> Upload & run
          </button>
          <input ref={fileInput} className="file-input" type="file" accept=".jsonl" disabled={busy || loading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(file, profile);
              event.currentTarget.value = '';
            }} />
        </div>
      </div>
      {source && (
        <div className="source-meta">
          <span className={`source-badge ${source.origin}`}>{source.origin}</span>
          <span>{source.row_count.toLocaleString()} input rows</span>
          <span>{(source.byte_count / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KiB</span>
          <span>Profile: {source.profile === 'oasst1' ? 'OASST1' : 'Standard'}</span>
          <a href={`/api/sources/${source.source_id}/download`} title="Download original JSONL">
            <Download size={15} /> Original JSONL
          </a>
        </div>
      )}
    </header>
  );
}
