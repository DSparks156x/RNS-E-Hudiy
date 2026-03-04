import { motion, useTransform } from 'framer-motion';
import { useLiveValue, LiveText } from './LiveText';

interface InjectionBarProps {
  groupKey: string;
  index: number;
}

export function InjectionBar({ groupKey, index }: InjectionBarProps) {
  const mv = useLiveValue(groupKey, index, 0);

  // Typical injection time at idle is ~1-3ms
  const maxTime = 10.0;

  const pctString = useTransform(mv, (val) => {
    const v = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? 0 : parseFloat(val));
    const p = Math.min((v / maxTime) * 100, 100);
    return `${p}%`;
  });

  const formatInj = (val: number | string) => {
    const v = typeof val === 'number' ? val : parseFloat(val);
    return !isNaN(v) && v > 0 ? v.toFixed(1) + ' ms' : '--';
  };

  return (
    <div className="inj-container">
      <div className="inj-header">
        <span className="inj-label">Injection Time</span>
        <LiveText className="inj-val" groupKey={groupKey} index={index} format={formatInj} />
      </div>
      <div className="inj-bar-wrapper">
        <div className="inj-bar-track">
          <motion.div
            className="inj-bar-fill"
            style={{ width: pctString }}
          />
        </div>
      </div>
    </div>
  );
}
