import { motion, useTransform, useSpring } from 'framer-motion';
import { useLiveValue } from './LiveText';

interface GaugeProps {
  id?: string;
  groupKey: string;
  index: number;
  min: number;
  max: number;
  label: string[];
  size?: number;
}

export function Gauge({ groupKey, index, min, max, label, size = 140 }: GaugeProps) {
  const mv = useLiveValue(groupKey, index, min);

  // SVG parameters
  const strokeWidth = 14;
  const radius = (size - strokeWidth) / 2;
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

  // We want the gauge to fill up from the start point.
  // By using `circum circum` for the dash array, we have one massive segment of ink
  // and one massive segment of space. We offset the pattern by `circum - visible_length`
  // so that only `visible_length` of ink remains to be drawn from path position 0.
  const dashoffset = useTransform(pct, (p: number) => circum - arcLength * p);

  // Center display formatted to 1 decimal place
  const displayVal = useTransform(mv, (val) => {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '--' : num.toFixed(1);
  });

  return (
    <div className="gauge-wrapper-md" style={{ position: 'relative', width: size, height: size * 0.85, margin: '0 auto' }}>
      <svg width={size} height={size} style={{ position: 'absolute', top: 0, left: 0 }}>
        {/* Background Arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#333"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${arcLength} ${circum}`}
          strokeDashoffset={0}
          transform={`rotate(${startAngleOffset} ${size/2} ${size/2})`}
        />
        {/* Foreground Animated Arc */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--accent-color)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${circum} ${circum}`}
          style={{ strokeDashoffset: dashoffset }}
          transform={`rotate(${startAngleOffset} ${size/2} ${size/2})`}
        />
      </svg>

      {/* Center value */}
      <motion.div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        x: '-50%',
        y: '-50%',
        color: '#fff',
        fontWeight: 'bold',
        fontSize: 22,
        fontFamily: 'monospace',
        pointerEvents: 'none',
      }}>
        {displayVal}
      </motion.div>

      {/* Sub-labels pushed below center */}
      <div style={{
        position: 'absolute',
        top: '75%',
        left: '50%',
        transform: 'translateX(-50%)',
        textAlign: 'center',
        pointerEvents: 'none',
        lineHeight: 1.2
      }}>
        {label.map((line) => (
          <div key={line} style={{ color: '#888', fontSize: 11, lineHeight: 1.3 }}>{line}</div>
        ))}
      </div>
    </div>
  );
}
