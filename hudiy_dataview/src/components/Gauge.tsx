import { motion, useTransform, useSpring } from 'framer-motion';
import { useLiveValue } from './LiveText';

interface GaugeProps {
  id?: string;
  groupKey: string;
  index: number;
  min: number;
  max: number;
  label: React.ReactNode[];
  sizeClass?: string;
  decimals?: number;
  markerGroupKey?: string;
  markerIndex?: number;
  markerDecimals?: number;
}

// Separate component so the hook is always called unconditionally
interface MarkerProps {
  groupKey: string;
  index: number;
  min: number;
  max: number;
  baseSize: number;
  radius: number;
  strokeWidth: number;
  circum: number;
  arcLength: number;
  startAngleOffset: number;
}

function GaugeMarker({ groupKey, index, min, max, baseSize, radius, strokeWidth, circum, arcLength, startAngleOffset }: MarkerProps) {
  const mv = useLiveValue(groupKey, index, min);

  const tickLen = 3;

  const rawOffset = useTransform(mv, (val) => {
    const num = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? min : parseFloat(val));
    const pct = Math.max(0, Math.min(1, (num - min) / (max - min)));
    const pos = arcLength * pct;
    return -(pos - tickLen / 2);
  });

  // Same spring physics as the main arc so the tick animates smoothly
  const dashoffset = useSpring(rawOffset, { stiffness: 150, damping: 25, restDelta: 0.001 });

  return (
    <motion.circle
      cx={baseSize / 2}
      cy={baseSize / 2}
      r={radius}
      fill="none"
      stroke="var(--primary)"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeDasharray={`${tickLen} ${circum}`}
      style={{ strokeDashoffset: dashoffset }}
      transform={`rotate(${startAngleOffset} ${baseSize / 2} ${baseSize / 2})`}
    />
  );
}

export function Gauge({ groupKey, index, min, max, label, sizeClass = '', decimals = 1, markerGroupKey, markerIndex, markerDecimals = 1 }: GaugeProps) {
  const mv = useLiveValue(groupKey, index, min);

  // SVG parameters (using a fixed 200x200 internal coordinate system)
  const baseSize = 200;
  const strokeWidth = 24;
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

  // Center display
  const displayVal = useTransform(mv, (val) => {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '--' : num.toFixed(decimals);
  });

  const showMarker = markerGroupKey !== undefined && markerIndex !== undefined;

  // Secondary value display (for the marker)
  const markerMv = useLiveValue(markerGroupKey || '', markerIndex || 0, min);
  const markerDisplayVal = useTransform(markerMv, (val) => {
    if (!showMarker) return '';
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '--' : num.toFixed(markerDecimals);
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
          stroke="var(--surface-dim)"
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
          stroke="var(--primary-fixed)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${circum} ${circum}`}
          style={{ strokeDashoffset: dashoffset }}
          transform={`rotate(${startAngleOffset} ${baseSize / 2} ${baseSize / 2})`}
        />
        {/* Ghost tick marker for secondary value */}
        {showMarker && (
          <GaugeMarker
            groupKey={markerGroupKey!}
            index={markerIndex!}
            min={min}
            max={max}
            baseSize={baseSize}
            radius={radius}
            strokeWidth={strokeWidth}
            circum={circum}
            arcLength={arcLength}
            startAngleOffset={startAngleOffset}
          />
        )}
      </svg>

      {/* Center values container */}
      <div className="gauge-center-container">
        {showMarker && (
          <motion.div className="gauge-secondary-val">
            {markerDisplayVal}
          </motion.div>
        )}
        <motion.div className="gauge-center-val">
          {displayVal}
        </motion.div>
      </div>

      {/* Sub-labels pushed below center */}
      <div className="gauge-labels-container">
        {label.map((line, i) => (
          <div key={i} className="gauge-label-line">{line}</div>
        ))}
      </div>
    </div>
  );
}
