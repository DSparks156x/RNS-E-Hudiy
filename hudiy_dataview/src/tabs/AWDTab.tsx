import { Gauge } from '../components/Gauge';
import { LiveText } from '../components/LiveText';

const fmtVal = (val: number | string, unit: string = '') => {
  const v = typeof val === 'number' ? val : parseFloat(val);
  return isNaN(v) ? '--' : `${v.toFixed(1)} ${unit}`;
};

export function AWDTab() {
  return (
    <section id="awd" className="tab-content active">
      <div className="awd-layout">
        {/* Group 3: Performance */}
        <div className="panel awd-main">
          <h3>Haldex Performance (Grp 3)</h3>
          <div className="gauges-row">
            <div className="gauge-wrapper">
              <Gauge id="gauge_awd_pres" groupKey="10:3" index={0} min={0} max={60} label={['Bar', 'Oil Pressure']} sizeClass="gauge-md" />
            </div>
            <div className="gauge-wrapper">
              <Gauge id="gauge_awd_torque" groupKey="10:3" index={1} min={0} max={2000} label={['Nm', 'Est. Torque']} sizeClass="gauge-md" />
            </div>
          </div>
          <div className="extra-vals-grid">
            <div className="col">
              <div className="val-row-sm">
                <span className="label">Valve (N273):</span>
                <span><LiveText groupKey="10:3" index={2} format={(v) => fmtVal(v, '%')} /></span>
              </div>
            </div>
            <div className="col">
              <div className="val-row-sm">
                <span className="label">Current (N273):</span>
                <span><LiveText groupKey="10:3" index={3} format={(v) => fmtVal(v, 'mA')} /></span>
              </div>
            </div>
          </div>
        </div>

        {/* Group 1: Status */}
        <div className="panel awd-status">
          <h3>System Status (Grp 1)</h3>
          <div className="val-list">
            <div className="val-row">
              <span className="label">Haldex Oil Temp</span>
              <span className="value"><LiveText groupKey="10:1" index={0} format={(v) => fmtVal(v, '°C')} /></span>
            </div>
            <div className="val-row">
              <span className="label">Plate Temp</span>
              <span className="value"><LiveText groupKey="10:1" index={1} format={(v) => fmtVal(v, '°C')} /></span>
            </div>
            <div className="val-row">
              <span className="label">Supply Voltage</span>
              <span className="value"><LiveText groupKey="10:1" index={2} format={(v) => fmtVal(v, 'V')} /></span>
            </div>
          </div>
        </div>

        {/* Group 5: Modes */}
        <div className="panel awd-modes">
          <h3>Modes (Grp 5)</h3>
          <div className="val-list">
            <div className="val-row">
              <span className="label">CAN Output</span>
              <span className="value sm"><LiveText groupKey="10:5" index={0} /></span>
            </div>
            <div className="val-row">
              <span className="label">Vehicle Mode</span>
              <span className="value sm"><LiveText groupKey="10:5" index={1} /></span>
            </div>
            <div className="val-row">
              <span className="label">Slip Control</span>
              <span className="value sm"><LiveText groupKey="10:5" index={2} /></span>
            </div>
            <div className="val-row">
              <span className="label">Op Mode</span>
              <span className="value sm"><LiveText groupKey="10:5" index={3} /></span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
