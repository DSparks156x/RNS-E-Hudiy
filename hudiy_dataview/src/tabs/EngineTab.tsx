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
  return (
    <section id="engine" className="tab-content active">
      <div className="engine-grid">

        {/* Left Column: Air & Boost */}
        <div className="engine-col">
          <div className="gauge-title">Mass Air Flow</div>
          <Gauge id="gauge_maf" valueId="engine.maf" min={0} max={400} label={['g/s', '']} sizeClass="gauge-md" />
          <div className="gauge-title">Boost</div>
          <Gauge id="gauge_boost" valueId="engine.boost.actual_absolute" min={0} max={3000} label={['mbar', <div style={{ display: 'flex', justifyContent: 'center', width: '120px', margin: '0 auto' }}><span style={{ flex: 1, textAlign: 'right', color: 'var(--on-surface)', fontWeight: 'bold' }}>Actual</span><span style={{ margin: '0 6px', opacity: 0.5 }}>|</span><span style={{ flex: 1, textAlign: 'left', color: 'var(--primary)', fontWeight: 'normal' }}>Specified</span></div>]} sizeClass="gauge-md" decimals={0} markerValueId="engine.boost.spec_absolute" markerDecimals={0} />
        </div>

        {/* Center Column: Performance */}
        <div className="engine-col perf-col">
          <div className="perf-top">
            <div className="rpm-display">
              <div className="gauge-title">Engine Speed</div>
              <span className="value-md"><LiveText valueId="engine.rpm" format={(v) => `${fmtInt(v)} /min`} /></span>
            </div>
            <div className="ign-display">
              <div className="gauge-title">Timing Advance</div>
              <span className="stat-value-lg"><LiveText valueId="engine.ignition_timing" format={fmtIgn} /></span>
            </div>
          </div>
          <KnockBars valueIds={[1, 2, 3, 4].map(c => `engine.timing_retard.cylinder${c}`)} />
        </div>

        {/* Right Column: Fuel */}
        <div className="engine-col">
          <div className="gauge-title">Fuel Pressure</div>
          <Gauge id="gauge_fuel" valueId="engine.fuel_rail.actual" min={0} max={150} label={['Bar', 'Actual']} sizeClass="gauge-sm" />
          <div className="stat-list">
            <div className="stat-row">
              <span className="stat-label">Specified</span>
              <span className="stat-value"><LiveText valueId="engine.fuel_rail.spec" format={(v) => `${fmtVal(v)} bar`} /></span>
            </div>
            <div className="stat-row">
              <span className="stat-label">Duty</span>
              <span className="stat-value"><LiveText valueId="engine.fuel_pump_duty" format={(v) => `${fmtVal(v)} %`} /></span>
            </div>
          </div>
          <InjectionBar valueId="engine.injection_time" />
        </div>

        {/* Bottom Row (Spans all 3 cols): Temps */}
        <div className="engine-temp-row">
          <div className="temp-item">
            <span className="stat-label">Oil</span>
            <span className="temp-val"><LiveText valueId="engine.oil_temperature" format={(v) => `${fmtInt(v)} °C`} /></span>
          </div>
          <div className="temp-item">
            <span className="stat-label">Ambient</span>
            <span className="temp-val"><LiveText valueId="ambient.filtered_temperature" format={(v) => `${fmtInt(v)} °C`} /></span>
          </div>
          <div className="temp-item">
            <span className="stat-label">Intake Air</span>
            <span className="temp-val"><LiveText valueId="engine.intake_temperature" format={(v) => `${fmtInt(v)} °C`} /></span>
          </div>
          <div className="temp-item">
            <span className="stat-label">Coolant</span>
            <span className="temp-val"><LiveText valueId="engine.coolant_temperature" format={(v) => `${fmtInt(v)} °C`} /></span>
          </div>
        </div>

      </div>
    </section>
  );
}
