import type { VocabEntry } from "../types";

interface Props {
  entries: VocabEntry[];
}

/** Minimal inline-SVG cumulative line chart of vocab growth over time —
 * deliberately no charting library dependency for one simple chart. */
export function GrowthChart({ entries }: Props) {
  const byDate = new Map<string, number>();
  for (const e of entries) {
    const date = e.first_seen_date;
    if (!date) continue;
    byDate.set(date, (byDate.get(date) ?? 0) + 1);
  }
  const dates = [...byDate.keys()].sort();

  if (dates.length === 0) {
    return <p className="growth-chart-empty">No dated vocab entries yet.</p>;
  }

  let cumulative = 0;
  const points = dates.map((date) => {
    cumulative += byDate.get(date)!;
    return { date, count: cumulative };
  });

  const width = 600;
  const height = 160;
  const padding = 24;
  const maxCount = points[points.length - 1].count;
  const xStep = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;

  const coords = points.map((p, i) => {
    const x = padding + i * xStep;
    const y = height - padding - (p.count / maxCount) * (height - padding * 2);
    return { ...p, x, y };
  });

  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="growth-chart" role="img" aria-label="Vocab growth over time">
      <path d={path} fill="none" stroke="currentColor" strokeWidth={2} />
      {coords.map((c) => (
        <circle key={c.date} cx={c.x} cy={c.y} r={3} fill="currentColor" />
      ))}
      <text x={padding} y={height - 4} fontSize={10}>
        {points[0].date}
      </text>
      <text x={width - padding} y={height - 4} fontSize={10} textAnchor="end">
        {points[points.length - 1].date}
      </text>
      <text x={padding} y={14} fontSize={10}>
        {maxCount} words
      </text>
    </svg>
  );
}
