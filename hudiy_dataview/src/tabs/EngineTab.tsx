import { Gauge } from '../components/Gauge';
import { KnockBars } from '../components/KnockBars';
import { InjectionBar } from '../components/InjectionBar';
import { LiveText } from '../components/LiveText';

const fmtVal = (val: number | string) => {
  const v = typeof val === 'number' ? val : parseFloat(val);
  return isNaN(v) ? '--' : v.toFixed(1);
};
const fmtInt = (val: number | string) => {
  const v = typeof val === 'number' ? val : parseInt(val, 10);
  return isNaN(v) ? '--' : Math.round(v).toString();
};
const fmtIgn = (val: number | string) => {
  const v = typeof val === 'number' ? val : parseFloat(val);
  return isNaN(v) ? '--' : `${v.toFixed(1)} °BTDC`;
};

export function EngineTab() {
  const tempLabels = ['Oil', 'Ambient', 'Intake Air', 'Coolant'];

  return (
    <section id="engine" className="tab-content active">
      <div className="engine-grid">

        {/* Left Column: Air & Boost */}
        <div className="engine-col">
          <div className="gauge-title">Mass Air Flow</div>
          <Gauge id="gauge_maf" groupKey="1:3" index={1} min={0} max={400} label={['g/s', '']} sizeClass="gauge-sm" />
          <div className="gauge-title">Boost</div>
          <Gauge id="gauge_boost" groupKey="1:115" index={3} min={0} max={3000} label={['mbar', 'Actual']} sizeClass="gauge-sm" />
          <div className="stat-list">
            <div className="stat-row">
              <span className="stat-label">Request</span>
              <span className="stat-value"><LiveText groupKey="1:115" index={2} format={(v) => `${fmtInt(v)} mbar`} /></span>
            </div>
          </div>
        </div>

        {/* Center Column: Performance */}
        <div className="engine-col perf-col">
          <div className="perf-top">
            <div className="rpm-display">
              <div className="stat-label">Engine Speed</div>
              <span className="value-md"><LiveText groupKey="1:3" index={0} format={(v) => `${fmtInt(v)} /min`} /></span>
            </div>
            <div className="ign-display">
              <div className="stat-label">Ignition</div>
              <span className="stat-value-lg"><LiveText groupKey="1:3" index={3} format={fmtIgn} /></span>
            </div>
          </div>
          <KnockBars groupKey="1:20" />
        </div>

        {/* Right Column: Fuel */}
        <div className="engine-col">
          <div className="gauge-title">Fuel Pressure</div>
          <Gauge id="gauge_fuel" groupKey="1:106" index={1} min={0} max={150} label={['Bar', 'Actual']} sizeClass="gauge-sm" />
          <div className="stat-list">
            <div className="stat-row">
              <span className="stat-label">Specified</span>
              <span className="stat-value"><LiveText groupKey="1:106" index={0} format={(v) => `${fmtVal(v)} bar`} /></span>
            </div>
            <div className="stat-row">
              <span className="stat-label">Duty</span>
              <span className="stat-value"><LiveText groupKey="1:106" index={2} format={(v) => `${fmtVal(v)} %`} /></span>
            </div>
          </div>
          <InjectionBar groupKey="1:2" index={2} />
        </div>

        {/* Bottom Row (Spans all 3 cols): Temps */}
        <div className="engine-temp-row">
          {tempLabels.map((label, i) => (
            <div key={label} className="temp-item">
              <span className="stat-label">{label}</span>
              <span className="temp-val"><LiveText groupKey="1:134" index={i} format={(v) => `${fmtInt(v)} °C`} /></span>
            </div>
          ))}
        </div>

      </div>
    </section>
  );
}
