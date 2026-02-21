import { DiagnosticMessage, DiagnosticValue } from '../types';
import { Gauge } from '../components/Gauge';
import { KnockBars } from '../components/KnockBars';
import { InjectionBar } from '../components/InjectionBar';

function numVal(v: DiagnosticValue | undefined): number {
  if (!v) return 0;
  if (typeof v.value === 'number') return v.value;
  const p = parseFloat(v.value);
  return isNaN(p) ? 0 : p;
}

function fmtVal(v: DiagnosticValue | undefined): string {
  if (!v) return '--';
  return `${typeof v.value === 'number' ? v.value.toFixed(1) : v.value} ${v.unit}`;
}

type DataMap = Record<string, DiagnosticMessage>;

interface EngineTabProps {
  data: DataMap;
}

export function EngineTab({ data }: EngineTabProps) {
  const grp3 = data['1:3'];
  const grp20 = data['1:20'];
  const grp106 = data['1:106'];
  const grp115 = data['1:115'];
  const grp134 = data['1:134'];
  const grp2 = data['1:2'];

  const rpm = fmtVal(grp3?.data[0]);
  const ign = fmtVal(grp3?.data[3]);
  const mafVal = numVal(grp3?.data[1]);

  const knockValues = [0, 1, 2, 3].map((i) => numVal(grp20?.data[i]));

  const fuelSpec = fmtVal(grp106?.data[0]);
  const fuelActual = numVal(grp106?.data[1]);
  const fuelDuty = fmtVal(grp106?.data[2]);
  const injTimeNum = numVal(grp2?.data[2]);

  const boostSpec = fmtVal(grp115?.data[2]);
  const boostActual = numVal(grp115?.data[3]);

  const temps = [0, 1, 2, 3].map((i) => fmtVal(grp134?.data[i]));
  const tempLabels = ['Oil', 'Ambient', 'Intake Air', 'Coolant'];

  return (
    <section id="engine" className="tab-content active">
      <div className="engine-layout">
        {/* Center: Boost */}
        <div className="panel boost-panel">
          <div className="gauge-title">Mass Air Flow</div>
          <Gauge id="gauge_maf" value={mafVal} min={0} max={400} label={['g/s', '']} />
          <div className="gauge-title">Boost</div>
          <Gauge id="gauge_boost" value={boostActual} min={0} max={3000} label={['mbar', 'Actual']} />
          <div className="stat-list">
            <div className="stat-row">
              <span className="stat-label">Request</span>
              <span className="stat-value">{boostSpec}</span>
            </div>
          </div>
        </div>

        {/* Left: Performance */}
        <div className="panel perf-panel">
          <div className="perf-top">
            <div className="rpm-display">
              <div className="stat-label">Engine Speed</div>
              <span className="value-md">{rpm}</span>
            </div>
            <div className="ign-display">
              <div className="stat-label">Ignition</div>
              <span className="stat-value-lg">{ign}</span>
            </div>
          </div>
          <KnockBars values={knockValues} />
        </div>

        {/* Right: Fuel */}
        <div className="panel fuel-panel">
          <div className="gauge-title">Fuel Pressure</div>
          <Gauge id="gauge_fuel" value={fuelActual} min={0} max={150} label={['Bar', 'Actual']} />
          <div className="stat-list">
            <div className="stat-row">
              <span className="stat-label">Specified</span>
              <span className="stat-value">{fuelSpec}</span>
            </div>
            <div className="stat-row">
              <span className="stat-label">Duty</span>
              <span className="stat-value">{fuelDuty}</span>
            </div>
          </div>
          <InjectionBar value={injTimeNum} />
        </div>

        {/* Bottom: Temps */}
        <div className="panel eng-temp-panel">
          {tempLabels.map((label, i) => (
            <div key={label} className="temp-item">
              <span className="stat-label">{label}</span>
              <span className="temp-val">{temps[i]}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
