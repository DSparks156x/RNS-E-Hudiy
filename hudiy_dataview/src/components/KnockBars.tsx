interface KnockBarsProps {
  values: number[]; // 4 values, degrees retard
}

function KnockBar({ cyl, value }: { cyl: number; value: number }) {
  const maxRetard = 12.0;
  const pct = Math.min((value / maxRetard) * 100, 100);
  const color =
    value <= 0.1 ? 'transparent' : value < 3 ? '#ffcc00' : '#ff0000';

  return (
    <div className="k-bar-wrapper">
      <div className="k-val">{value > 0.1 ? value.toFixed(1) : ''}</div>
      <div className="k-bar-track">
        <div
          className="k-bar"
          style={{ height: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <div className="k-label">{cyl}</div>
    </div>
  );
}

export function KnockBars({ values }: KnockBarsProps) {
  return (
    <div className="knock-container">
      <div className="knock-header">Timing Pull</div>
      <div className="knock-bars">
        {values.map((v, i) => (
          <KnockBar key={i} cyl={i + 1} value={v} />
        ))}
      </div>
    </div>
  );
}
