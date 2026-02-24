import { motion, useTransform, useSpring } from 'framer-motion';
import { useLiveValue } from './LiveText';

interface GaugeProps {
  id?: string;
  groupKey: string;
  index: number;
  min: number;
  max: number;
  label: string[];
  sizeClass?: string;
}

export function Gauge({ groupKey, index, min, max, label, sizeClass = '' }: GaugeProps) {
  const mv = useLiveValue(groupKey, index, min);

  // SVG parameters (using a fixed 200x200 internal coordinate system)
  const baseSize = 200;
  const strokeWidth = 16;
  const radius = (baseSize - strokeWidth) / 2;
  const circum = 2 * Math.PI * radius;

  // Recharts was startAngle=210, endAngle=-30. Range = 240 degrees.
  const angleRange = 240;
  const startAngleOffset = 150; // SVG 0 is right (3 o'clock). 210 degrees CCW is +150 deg CW.

  // Transform raw value into percentage fill [0, 1]
  const rawPct = useTransform(mv, (val) => {
    const num = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? 0 : parseFloat(val));
    return Math.max(0, Math.min(1, (num - min) / (max - min)));
  });

  // Apply a spring physics layer to the percentage so the needle moves smoothly
  const pct = useSpring(rawPct, { stiffness: 150, damping: 25, restDelta: 0.001 });

  // Dashoffset: 0 means full visible arc, circum means hidden arc. 
  const arcLength = circum * (angleRange / 360);

  const dashoffset = useTransform(pct, (p: number) => circum - arcLength * p);

  // Center display formatted to 1 decimal place
  const displayVal = useTransform(mv, (val) => {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '--' : num.toFixed(1);
  });

  return (
    <div className={`gauge-container-responsive ${sizeClass}`}>
      <svg
        viewBox={`0 0 ${baseSize} ${baseSize}`}
        className="gauge-svg"
      >
        {/* Background Arc */}
        <circle
          cx={baseSize / 2}
          cy={baseSize / 2}
          r={radius}
          fill="none"
          stroke="#333"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${arcLength} ${circum}`}
          strokeDashoffset={0}
          transform={`rotate(${startAngleOffset} ${baseSize / 2} ${baseSize / 2})`}
        />
        {/* Foreground Animated Arc */}
        <motion.circle
          cx={baseSize / 2}
          cy={baseSize / 2}
          r={radius}
          fill="none"
          stroke="var(--accent-color)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${circum} ${circum}`}
          style={{ strokeDashoffset: dashoffset }}
          transform={`rotate(${startAngleOffset} ${baseSize / 2} ${baseSize / 2})`}
        />
      </svg>

      {/* Center value */}
      <motion.div className="gauge-center-val">
        {displayVal}
      </motion.div>

      {/* Sub-labels pushed below center */}
      <div className="gauge-labels-container">
        {label.map((line) => (
          <div key={line} className="gauge-label-line">{line}</div>
        ))}
      </div>
    </div>
  );
}
