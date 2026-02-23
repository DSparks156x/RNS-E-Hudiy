import { Gauge } from '../components/Gauge';
import { SelectorBars } from '../components/SelectorBars';
import { LiveText } from '../components/LiveText';

const fmtVal = (val: number | string, unit: string = '') => {
  const v = typeof val === 'number' ? val : parseFloat(val);
  return isNaN(v) ? '--' : `${v.toFixed(1)} ${unit}`;
};

const StringText = ({ groupKey, index, unit = '' }: { groupKey: string; index: number; unit?: string }) => (
  <LiveText 
    groupKey={groupKey} 
    index={index} 
    format={(v) => {
      if (typeof v === 'string' && isNaN(parseFloat(v))) return v;
      return fmtVal(v, unit);
    }} 
  />
);

export function TransmissionTab() {
  const tempLabels = ['Fluid', 'Module', 'Clutch Oil', 'Status'];

  return (
    <section id="transmission" className="tab-content active">
      <div className="trans-layout">
        {/* Clutches */}
        <div className="panel pressure-panel">
          <h3>Clutches</h3>
          <div className="gauges-row">
            <div className="gauge-wrapper">
              <Gauge id="gauge_pres_1" groupKey="2:11" index={3} min={0} max={20} label={['Bar', 'Clutch 1']} />
            </div>
            <div className="gauge-wrapper">
              <Gauge id="gauge_pres_2" groupKey="2:12" index={3} min={0} max={20} label={['Bar', 'Clutch 2']} />
            </div>
          </div>
          <div className="extra-vals-grid">
            <div className="col">
              <div className="val-row-sm"><span className="label">Speed 1</span> <span><StringText groupKey="2:11" index={0} unit="/min" /></span></div>
              <div className="val-row-sm"><span className="label">Torque 1</span> <span><StringText groupKey="2:11" index={1} unit="Nm" /></span></div>
              <div className="val-row-sm"><span className="label">Amps 1</span> <span><StringText groupKey="2:11" index={2} unit="A" /></span></div>
            </div>
            <div className="col">
              <div className="val-row-sm"><span className="label">Speed 2</span> <span><StringText groupKey="2:12" index={0} unit="/min" /></span></div>
              <div className="val-row-sm"><span className="label">Torque 2</span> <span><StringText groupKey="2:12" index={1} unit="Nm" /></span></div>
              <div className="val-row-sm"><span className="label">Amps 2</span> <span><StringText groupKey="2:12" index={2} unit="A" /></span></div>
            </div>
          </div>
        </div>

        {/* Selector */}
        <div className="panel selector-panel">
          <h3>Selector Travel (Grp 16)</h3>
          <SelectorBars
            groupKey="2:16"
            topLabels={['1', '2', '5', '6']}
            botLabels={['3', '4', 'N', 'R']}
          />
        </div>

        {/* Temps */}
        <div className="engine-temp-row">
          {tempLabels.map((label, i) => (
            <div key={label} className="temp-item">
              <span className="stat-label">{label}</span>
              <span className="temp-val"><StringText groupKey="2:19" index={i} unit={(i < 3) ? '°C' : ''} /></span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
