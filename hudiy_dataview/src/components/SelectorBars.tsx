interface SelectorBarsProps {
  // 4 values: -9 to 9 (travel in mm)
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
  const clamped = Math.max(-9, Math.min(9, value));
  // Map ±9 to 50% of the track (fills half the track at max)
  const fillPct = (Math.abs(clamped) / 9) * 50;
  const isPositive = clamped >= 0;

  // Anchored at center, grows outward — left/right:0 pins width to track exactly
  const upperStyle: React.CSSProperties = {
    position: 'absolute',
    bottom: '50%',
    left: 0,
    right: 0,
    height: isPositive ? `${fillPct}%` : '0%',
    backgroundColor: 'var(--accent-color)',
    transition: 'height var(--rx-interval, 200ms) ease-out',
  };

  const lowerStyle: React.CSSProperties = {
    position: 'absolute',
    top: '50%',
    left: 0,
    right: 0,
    height: !isPositive ? `${fillPct}%` : '0%',
    backgroundColor: 'var(--text-color)', // Using text-color instead of hardcoded blue for now so it matches theme
    opacity: 0.8,
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
