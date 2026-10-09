import { motion, useTransform } from 'framer-motion';
import { useLiveValue } from './LiveText';

interface KnockBarsProps {
  groupKey?: string;
  valueIds?: string[];
}

function KnockBar({ cyl, groupKey, index, valueId }: { cyl: number; groupKey: string; index: number; valueId?: string }) {
  const mv = useLiveValue(groupKey, index, 0, valueId);

  const maxRetard = 12.0;

  // pct of the bar height
  const pct = useTransform(mv, (val) => {
    let v = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? 0 : parseFloat(val));
    v = Math.abs(v);
    return Math.min((v / maxRetard) * 100, 100);
  });

  const color = useTransform(mv, (val) => {
    let v = typeof val === 'number' ? val : parseFloat(val as string);
    v = Math.abs(v);
    if (isNaN(v) || v <= 0.1) return 'transparent';
    if (v < 5) return 'var(--surface-tint)';
    if (v < 10) return 'var(--tertiary-fixed)';
    return 'var(--error-container)';
  });

  const displayVal = useTransform(mv, (val) => {
    let v = typeof val === 'number' ? val : parseFloat(val);
    v = Math.abs(v);
    return isNaN(v) ? '--' : v > 0.1 ? v.toFixed(1) : '';
  });

  return (
    <div className="k-bar-wrapper">
      <motion.div className="k-val">{displayVal}</motion.div>
      <div className="k-bar-track">
        <motion.div
          className="k-bar"
          style={{ height: useTransform(pct, p => `${p}%`), backgroundColor: color }}
        />
      </div>
      <div className="k-label">{cyl}</div>
    </div>
  );
}

export function KnockBars({ groupKey = '', valueIds }: KnockBarsProps) {
  return (
    <div className="knock-container">
      <div className="knock-header">Timing Pull</div>
      <div className="knock-bars">
        {[0, 1, 2, 3].map((i) => (
          <KnockBar key={i} cyl={i + 1} groupKey={groupKey} index={valueIds ? 0 : i} valueId={valueIds?.[i]} />
        ))}
      </div>
    </div>
  );
}
