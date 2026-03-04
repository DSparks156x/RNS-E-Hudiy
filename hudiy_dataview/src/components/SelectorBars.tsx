import { motion, useTransform } from 'framer-motion';
import { useLiveValue } from './LiveText';

interface SelectorBarsProps {
  // We look into groupKey[0..3]
  groupKey: string;
  topLabels: string[];
  botLabels: string[];
}

function SelectorBar({
  groupKey,
  index,
  topLabel,
  botLabel,
}: {
  groupKey: string;
  index: number;
  topLabel: string;
  botLabel: string;
}) {
  const mv = useLiveValue(groupKey, index, 0);

  // Calculate the actual string percentages for motion styles
  // We need to multiply the boolean (0/100%) with the fillPct to get the right string.
  // Actually, we can just use another transform instead of multiplying strings.

  const posHeight = useTransform(mv, (val) => {
    const v = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? 0 : parseFloat(val));
    const clamped = Math.max(-8, Math.min(8, v));
    return clamped >= 0 ? `${(Math.abs(clamped) / 8) * 50}%` : '0%';
  });

  const negHeight = useTransform(mv, (val) => {
    const v = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? 0 : parseFloat(val));
    const clamped = Math.max(-8, Math.min(8, v));
    return clamped < 0 ? `${(Math.abs(clamped) / 8) * 50}%` : '0%';
  });

  return (
    <div className="bar-wrapper">
      <span className="bar-label-top">{topLabel}</span>
      <div className="bar-track">
        <motion.div
          className="bar-fill-pos"
          style={{
            position: 'absolute',
            bottom: '50%',
            left: 0,
            right: 0,
            height: posHeight,
            backgroundColor: 'var(--primary-fixed)'
          }}
        />
        <div className="bar-centre-line" />
        <motion.div
          className="bar-fill-neg"
          style={{
            position: 'absolute',
            top: '50%',
            left: 0,
            right: 0,
            height: negHeight,
            backgroundColor: 'var(--primary)', // match theme
            opacity: 0.8
          }}
        />
      </div>
      <span className="bar-label-bot">{botLabel}</span>
    </div>
  );
}

export function SelectorBars({ groupKey, topLabels, botLabels }: SelectorBarsProps) {
  return (
    <div className="bar-container">
      {[0, 1, 2, 3].map((i) => (
        <SelectorBar
          key={i}
          groupKey={groupKey}
          index={i}
          topLabel={topLabels[i] ?? String(i + 1)}
          botLabel={botLabels[i] ?? ''}
        />
      ))}
    </div>
  );
}
