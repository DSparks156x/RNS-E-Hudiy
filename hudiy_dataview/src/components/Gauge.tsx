import { RadialBarChart, RadialBar, PolarAngleAxis } from 'recharts';

interface GaugeProps {
  id?: string;
  value: number;
  min: number;
  max: number;
  label: string[];
  size?: number;
}

export function Gauge({ value, min, max, label, size = 140 }: GaugeProps) {
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  const svgHeight = size * 0.85;

  return (
    <div className="gauge-wrapper-md" style={{ position: 'relative', width: size, height: svgHeight, margin: '0 auto' }}>
      <RadialBarChart
        width={size}
        height={svgHeight}
        cx={size / 2}
        cy={size / 2}
        innerRadius={size / 2 - 20}
        outerRadius={size / 2 - 3} // Made slightly thicker (outerRadius increased)
        data={[{ value: pct }]}
        startAngle={210}
        endAngle={-30}
      >
        {/* Domain 0-100 so the bar represents percentage fill */}
        <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
        <RadialBar
          background={{ fill: '#333' }}
          dataKey="value"
          cornerRadius={4}
          fill="#ff3b3b"
          angleAxisId={0}
          isAnimationActive={false}
        />
      </RadialBarChart>

      {/* Center value */}
      <div style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        color: '#fff',
        fontWeight: 'bold',
        fontSize: 22,
        fontFamily: 'monospace',
        pointerEvents: 'none',
      }}>
        {value.toFixed(1)}
      </div>

      {/* Sub-labels pushed below center */}
      <div style={{
        position: 'absolute',
        top: '75%', /* Adjusted for new compressed vertical bounding box */
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
