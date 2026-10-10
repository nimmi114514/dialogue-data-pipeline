import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { useState } from 'react';
import { PAGE_SIZE } from '../api';
import type { CleanedRecord, Page, RejectedRecord } from '../types';

type Props = {
  records: Page<CleanedRecord>;
  rejected: Page<RejectedRecord>;
  selected: CleanedRecord | RejectedRecord | null;
  onSelect: (item: CleanedRecord | RejectedRecord) => void;
  recordPage: number;
  rejectedPage: number;
  recordsLoading: boolean;
  rejectedLoading: boolean;
  onRecordPage: (page: number) => void;
  onRejectedPage: (page: number) => void;
};

export function DataTables(props: Props) {
  const { records, rejected, selected, onSelect } = props;
  return (
    <section className="table-layout">
      <div className="panel records-panel" aria-busy={props.recordsLoading}>
        <h2>Cleaned Records <span>{records.total.toLocaleString()}</span></h2>
        <div className="table-wrap">
          <table aria-label="Cleaned records">
            <thead><tr><th>Line</th><th>Sample</th><th>Topic</th><th>Split</th><th>Chars</th></tr></thead>
            <tbody>
              {records.items.map((record) => (
                <tr key={record.sample_id} className={selected === record ? 'selected' : ''}>
                  <td>{record.line_number}</td>
                  <td><button className="row-button" onClick={() => onSelect(record)} title={record.sample_id}>{record.sample_id}</button></td>
                  <td>{record.topic}</td><td>{record.split ?? '-'}</td><td>{record.char_count}</td>
                </tr>
              ))}
              {!records.items.length && <tr><td colSpan={5} className="table-empty">{props.recordsLoading ? 'Loading...' : 'No records'}</td></tr>}
            </tbody>
          </table>
        </div>
        <Pagination label="Cleaned records" total={records.total} page={props.recordPage} loading={props.recordsLoading} onChange={props.onRecordPage} />
      </div>
      <div className="panel records-panel" aria-busy={props.rejectedLoading}>
        <h2>Rejected / Duplicate <span>{rejected.total.toLocaleString()}</span></h2>
        <div className="table-wrap">
          <table aria-label="Rejected records">
            <thead><tr><th>Line</th><th>Status</th><th>Rule</th></tr></thead>
            <tbody>
              {rejected.items.map((item) => (
                <tr key={`${item.line_number}-${item.status}`} className={selected === item ? 'selected' : ''}>
                  <td><button className="row-button" onClick={() => onSelect(item)}>{item.line_number}</button></td>
                  <td><span className={`status-badge ${item.status}`}>{item.status}</span></td>
                  <td>{item.reasons[0]?.rule_id ?? '-'}</td>
                </tr>
              ))}
              {!rejected.items.length && <tr><td colSpan={3} className="table-empty">{props.rejectedLoading ? 'Loading...' : 'No records'}</td></tr>}
            </tbody>
          </table>
        </div>
        <Pagination label="Rejected records" total={rejected.total} page={props.rejectedPage} loading={props.rejectedLoading} onChange={props.onRejectedPage} />
      </div>
      <DetailPanel selected={selected} />
    </section>
  );
}

function Pagination({ label, total, page, loading, onChange }: {
  label: string; total: number; page: number; loading: boolean; onChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  return (
    <nav className="pagination" aria-label={`${label} pagination`}>
      <span>{loading ? 'Loading...' : `${total ? page * PAGE_SIZE + 1 : 0}–${Math.min(total, (page + 1) * PAGE_SIZE)} of ${total.toLocaleString()}`}</span>
      <div>
        <button title="First page" aria-label="First page" disabled={loading || page === 0} onClick={() => onChange(0)}><ChevronsLeft size={16} /></button>
        <button title="Previous page" aria-label="Previous page" disabled={loading || page === 0} onClick={() => onChange(page - 1)}><ChevronLeft size={16} /></button>
        <span>{page + 1} / {pages}</span>
        <button title="Next page" aria-label="Next page" disabled={loading || page >= pages - 1} onClick={() => onChange(page + 1)}><ChevronRight size={16} /></button>
        <button title="Last page" aria-label="Last page" disabled={loading || page >= pages - 1} onClick={() => onChange(pages - 1)}><ChevronsRight size={16} /></button>
      </div>
    </nav>
  );
}

function DetailPanel({ selected }: { selected: CleanedRecord | RejectedRecord | null }) {
  const [mode, setMode] = useState<'conversation' | 'json'>('conversation');
  let messages = selected && 'messages' in selected ? selected.messages : null;
  if (selected && 'raw_text' in selected) {
    try {
      const raw = JSON.parse(selected.raw_text);
      if (Array.isArray(raw?.messages) && raw.messages.every((item: unknown) =>
        item && typeof item === 'object' && 'role' in item && typeof item.role === 'string' &&
        'content' in item && typeof item.content === 'string')) messages = raw.messages;
    } catch { /* Malformed JSON is shown verbatim below. */ }
  }
  return (
    <div className="panel detail-panel">
      <div className="detail-heading">
        <h2>Record Detail</h2>
        <div className="segmented" aria-label="Detail view">
          <button aria-pressed={mode === 'conversation'} onClick={() => setMode('conversation')}>Conversation</button>
          <button aria-pressed={mode === 'json'} onClick={() => setMode('json')}>JSON</button>
        </div>
      </div>
      {!selected ? <div className="empty-state">No record selected</div> : mode === 'json' ? (
        <pre>{JSON.stringify(selected, null, 2)}</pre>
      ) : (
        <>
          <div className="detail-meta">
            <span>Line {selected.line_number}</span>
            {'sample_id' in selected && <code>{selected.sample_id}</code>}
          </div>
          {'reasons' in selected && <ul className="reason-list">{selected.reasons.map((reason, index) => (
            <li key={index}><strong>{reason.rule_id}</strong> · {reason.field_path}<p>{reason.reason}</p></li>
          ))}</ul>}
          {messages ? <div className="conversation">{messages.map((item, index) => (
            <div className={`message ${item.role}`} key={index}><span>{item.role}</span><p>{item.content}</p></div>
          ))}</div> : <pre>{'raw_text' in selected ? selected.raw_text : JSON.stringify(selected, null, 2)}</pre>}
        </>
      )}
    </div>
  );
}
