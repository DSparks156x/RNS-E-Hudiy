import { Gauge } from '../components/Gauge';
import { SelectorBars } from '../components/SelectorBars';
import { LiveText } from '../components/LiveText';

const fmtVal = (val: number | string, unit: string = '') => {
  const v = typeof val === 'number' ? val : parseFloat(val);
  return isNaN(v) ? '--' : `${v.toFixed(1)} ${unit}`;
};

const StringText = ({ valueId, unit = '' }: { valueId: string; unit?: string }) => (
  <LiveText
    valueId={valueId}
    format={(v) => {
      if (typeof v === 'string' && isNaN(parseFloat(v))) return v;
      return fmtVal(v, unit);
    }}
  />
);

export function TransmissionTab() {
  const tempLabels = ['Fluid', 'Module', 'Clutch Oil', 'Status'];
  const tempValues = ['transmission.fluid_temperature', 'transmission.module_temperature',
    'transmission.clutch_oil_temperature', 'transmission.idle_status'];

  return (
    <section id="transmission" className="tab-content active">
      <div className="trans-layout">
        {/* Clutches */}
        <div className="panel pressure-panel">
          <h3>Clutches</h3>
          <div className="gauges-row">
            <div className="gauge-wrapper">
              <Gauge id="gauge_pres_1" valueId="transmission.clutch1.actual_pressure" min={0} max={15} label={['Bar', 'Clutch 1']} sizeClass="gauge-md" deadzone={0.1} />
            </div>
            <div className="gauge-wrapper">
              <Gauge id="gauge_pres_2" valueId="transmission.clutch2.actual_pressure" min={0} max={15} label={['Bar', 'Clutch 2']} sizeClass="gauge-md" deadzone={0.1} />
            </div>
          </div>
          <div className="extra-vals-grid">
            <div className="col">
              <div className="val-row-sm"><span className="label">Speed 1</span> <span><StringText valueId="transmission.clutch1.shaft_speed" unit="/min" /></span></div>
              <div className="val-row-sm"><span className="label">Spec. Torque 1</span> <span><StringText valueId="transmission.clutch1.specified_torque" unit="Nm" /></span></div>
              <div className="val-row-sm"><span className="label">Amps 1</span> <span><StringText valueId="transmission.clutch1.valve_current" unit="A" /></span></div>
            </div>
            <div className="col">
              <div className="val-row-sm"><span className="label">Speed 2</span> <span><StringText valueId="transmission.clutch2.shaft_speed" unit="/min" /></span></div>
              <div className="val-row-sm"><span className="label">Spec. Torque 2</span> <span><StringText valueId="transmission.clutch2.specified_torque" unit="Nm" /></span></div>
              <div className="val-row-sm"><span className="label">Amps 2</span> <span><StringText valueId="transmission.clutch2.valve_current" unit="A" /></span></div>
            </div>
          </div>
        </div>

        {/* Selector */}
        <div className="panel selector-panel">
          <h3>Selector Travel</h3>
          <SelectorBars
            valueIds={['transmission.selector.1_3.travel_distance', 'transmission.selector.2_4.travel_distance',
              'transmission.selector.5_n.travel_distance', 'transmission.selector.6_r.travel_distance']}
            topLabels={['1', '4', '5', '6']}
            botLabels={['3', '2', 'N', 'R']}
          />
        </div>

        {/* Temps */}
        <div className="engine-temp-row">
          {tempLabels.map((label, i) => (
            <div key={label} className="temp-item">
              <span className="stat-label">{label}</span>
              <span className="temp-val">{i < 3
                ? <StringText valueId={tempValues[i]} unit="°C" />
                : <LiveText valueId={tempValues[i]} format={String} />}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
