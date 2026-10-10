import { Upload } from 'lucide-react';

type Props = {
  busy: boolean;
  error: string | null;
  onUpload: (file: File) => void;
};

export function UploadPanel({ busy, error, onUpload }: Props) {
  return (
    <section className="upload-panel">
      <div>
        <h1>Dialogue Data Pipeline</h1>
        <p>Upload a JSONL file, run the Python pipeline, and inspect the quality results.</p>
      </div>
      <label className="upload-button">
        <Upload size={18} />
        <span>{busy ? 'Processing...' : 'Upload JSONL'}</span>
        <input
          type="file"
          accept=".jsonl"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
            event.currentTarget.value = '';
          }}
        />
      </label>
      {error && <div className="error">{error}</div>}
    </section>
  );
}
