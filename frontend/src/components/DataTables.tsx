import type { CleanedRecord, RejectedRecord } from '../types';

type Props = {
  records: CleanedRecord[];
  rejected: RejectedRecord[];
  selected: CleanedRecord | RejectedRecord | null;
  onSelect: (item: CleanedRecord | RejectedRecord) => void;
};

export function DataTables({ records, rejected, selected, onSelect }: Props) {
  return (
    <section className="table-layout">
      <div className="panel">
        <h2>Cleaned Records</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Line</th>
                <th>Sample</th>
                <th>Topic</th>
                <th>Chars</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => (
                <tr key={record.sample_id} onClick={() => onSelect(record)}>
                  <td>{record.line_number}</td>
                  <td>{record.sample_id}</td>
                  <td>{record.topic}</td>
                  <td>{record.char_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="panel">
        <h2>Rejected / Duplicate</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Line</th>
                <th>Status</th>
                <th>Rule</th>
              </tr>
            </thead>
            <tbody>
              {rejected.map((item) => (
                <tr key={`${item.line_number}-${item.status}`} onClick={() => onSelect(item)}>
                  <td>{item.line_number}</td>
                  <td>{item.status}</td>
                  <td>{item.reasons[0]?.rule_id ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <DetailPanel selected={selected} />
    </section>
  );
}

function DetailPanel({ selected }: { selected: CleanedRecord | RejectedRecord | null }) {
  return (
    <div className="panel detail-panel">
      <h2>Detail</h2>
      {!selected ? (
        <div className="empty-state">Select a row</div>
      ) : (
        <pre>{JSON.stringify(selected, null, 2)}</pre>
      )}
    </div>
  );
}
