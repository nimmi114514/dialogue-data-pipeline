import type { Summary } from '../types';

type Props = {
  summary: Summary | null;
};

export function SummaryCards({ summary }: Props) {
  const cards = [
    ['Candidate lines', summary?.candidate_lines],
    ['Kept', summary?.kept_count],
    ['Duplicate', summary?.duplicate_count],
    ['Quarantined', summary?.quarantined_count],
    ['Blank lines', summary?.blank_lines],
  ];

  return (
    <section className="summary-grid">
      {cards.map(([label, value]) => (
        <div className="metric-card" key={label}>
          <div className="metric-label">{label}</div>
          <div className="metric-value">{value ?? '-'}</div>
        </div>
      ))}
    </section>
  );
}
