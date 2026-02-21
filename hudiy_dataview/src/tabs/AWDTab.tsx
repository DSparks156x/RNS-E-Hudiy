import { DiagnosticMessage, DiagnosticValue } from '../types';
import { Gauge } from '../components/Gauge';

type DataMap = Record<string, DiagnosticMessage>;

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

interface AWDTabProps {
  data: DataMap;
}

export function AWDTab({ data }: AWDTabProps) {
  const grp1 = data['34:1'];
  const grp3 = data['34:3'];
  const grp5 = data['34:5'];

  const awdPres = numVal(grp3?.data[0]);
  const awdTorque = numVal(grp3?.data[1]);

  return (
    <section id="awd" className="tab-content active">
      <div className="awd-layout">
        {/* Group 3: Performance */}
        <div className="panel awd-main">
          <h3>Haldex Performance (Grp 3)</h3>
          <div className="gauges-row">
            <div className="gauge-wrapper">
              <Gauge id="gauge_awd_pres" value={awdPres} min={0} max={60} label={['Bar', 'Oil Pressure']} />
            </div>
            <div className="gauge-wrapper">
              <Gauge id="gauge_awd_torque" value={awdTorque} min={0} max={2000} label={['Nm', 'Est. Torque']} />
            </div>
          </div>
          <div className="extra-vals-grid">
            <div className="col">
              <div className="val-row-sm"><span className="label">Valve (N273):</span> <span>{fmtVal(grp3?.data[2])}</span></div>
            </div>
            <div className="col">
              <div className="val-row-sm"><span className="label">Current (N273):</span> <span>{fmtVal(grp3?.data[3])}</span></div>
            </div>
          </div>
        </div>

        {/* Group 1: Status */}
        <div className="panel awd-status">
          <h3>System Status (Grp 1)</h3>
          <div className="val-list">
            {[
              { label: 'Haldex Oil Temp', idx: 0 },
              { label: 'Plate Temp', idx: 1 },
              { label: 'Supply Voltage', idx: 2 },
            ].map(({ label, idx }) => (
              <div key={label} className="val-row">
                <span className="label">{label}</span>
                <span className="value">{fmtVal(grp1?.data[idx])}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Group 5: Modes */}
        <div className="panel awd-modes">
          <h3>Modes (Grp 5)</h3>
          <div className="val-list">
            {[
              { label: 'CAN Output', idx: 0 },
              { label: 'Vehicle Mode', idx: 1 },
              { label: 'Slip Control', idx: 2 },
              { label: 'Op Mode', idx: 3 },
            ].map(({ label, idx }) => (
              <div key={label} className="val-row">
                <span className="label">{label}</span>
                <span className="value sm">{fmtVal(grp5?.data[idx])}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
