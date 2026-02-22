interface SelectorBarsProps {
  // 4 values: -100 to 100 (travel in mm)
  values: number[];
  topLabels: string[];
  botLabels: string[];
}

function SelectorBar({
  value,
  topLabel,
  botLabel,
}: {
  value: number;
  topLabel: string;
  botLabel: string;
}) {
  const clamped = Math.max(-100, Math.min(100, value));
  // Map ±100 to 50% of the track (fills half the track at max)
  const fillPct = Math.abs(clamped) / 2;
  const isPositive = clamped >= 0;

  // Anchored at center, grows outward — left/right:0 pins width to track exactly
  const upperStyle: React.CSSProperties = {
    position: 'absolute',
    bottom: '50%',
    left: 0,
    right: 0,
    height: isPositive ? `${fillPct}%` : '0%',
    backgroundColor: '#ff3b3b',
    transition: 'height var(--rx-interval, 200ms) ease-out',
  };

  const lowerStyle: React.CSSProperties = {
    position: 'absolute',
    top: '50%',
    left: 0,
    right: 0,
    height: !isPositive ? `${fillPct}%` : '0%',
    backgroundColor: '#3b3bff',
    transition: 'height var(--rx-interval, 200ms) ease-out',
  };

  return (
    <div className="bar-wrapper">
      <span className="bar-label-top">{topLabel}</span>
      <div className="bar-track">
        <div className="bar-fill-pos" style={upperStyle} />
        <div className="bar-centre-line" />
        <div className="bar-fill-neg" style={lowerStyle} />
      </div>
      <span className="bar-label-bot">{botLabel}</span>
    </div>
  );
}

export function SelectorBars({ values, topLabels, botLabels }: SelectorBarsProps) {
  return (
    <div className="bar-container">
      {values.map((v, i) => (
        <SelectorBar
          key={i}
          value={v}
          topLabel={topLabels[i] ?? String(i + 1)}
          botLabel={botLabels[i] ?? ''}
        />
      ))}
    </div>
  );
}
