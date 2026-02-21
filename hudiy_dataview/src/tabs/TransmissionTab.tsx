import { DiagnosticMessage, DiagnosticValue } from '../types';
import { Gauge } from '../components/Gauge';
import { SelectorBars } from '../components/SelectorBars';

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

interface TransmissionTabProps {
  data: DataMap;
}

export function TransmissionTab({ data }: TransmissionTabProps) {
  const grp11 = data['2:11'];
  const grp12 = data['2:12'];
  const grp16 = data['2:16'];
  const grp19 = data['2:19'];

  const c1Pres = numVal(grp11?.data[3]);
  const c2Pres = numVal(grp12?.data[3]);

  const selectorValues = [0, 1, 2, 3].map((i) => numVal(grp16?.data[i]));
  const temps = [0, 1, 2, 3].map((i) => fmtVal(grp19?.data[i]));
  const tempLabels = ['Fluid', 'Module', 'Clutch Oil', 'Status'];

  return (
    <section id="transmission" className="tab-content active">
      <div className="trans-layout">
        {/* Clutches */}
        <div className="panel pressure-panel">
          <h3>Clutches</h3>
          <div className="gauges-row">
            <div className="gauge-wrapper">
              <Gauge id="gauge_pres_1" value={c1Pres} min={0} max={20} label={['Bar', 'Clutch 1']} />
            </div>
            <div className="gauge-wrapper">
              <Gauge id="gauge_pres_2" value={c2Pres} min={0} max={20} label={['Bar', 'Clutch 2']} />
            </div>
          </div>
          <div className="extra-vals-grid">
            <div className="col">
              <div className="val-row-sm"><span className="label">Speed 1</span> <span>{fmtVal(grp11?.data[0])}</span></div>
              <div className="val-row-sm"><span className="label">Torque 1</span> <span>{fmtVal(grp11?.data[1])}</span></div>
              <div className="val-row-sm"><span className="label">Amps 1</span> <span>{fmtVal(grp11?.data[2])}</span></div>
            </div>
            <div className="col">
              <div className="val-row-sm"><span className="label">Speed 2</span> <span>{fmtVal(grp12?.data[0])}</span></div>
              <div className="val-row-sm"><span className="label">Torque 2</span> <span>{fmtVal(grp12?.data[1])}</span></div>
              <div className="val-row-sm"><span className="label">Amps 2</span> <span>{fmtVal(grp12?.data[2])}</span></div>
            </div>
          </div>
        </div>

        {/* Selector */}
        <div className="panel selector-panel">
          <h3>Selector Travel (Grp 16)</h3>
          <SelectorBars
            values={selectorValues}
            topLabels={['1', '2', '5', '6']}
            botLabels={['3', '4', 'N', 'R']}
          />
        </div>

        {/* Temps */}
        <div className="engine-temp-row">
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
