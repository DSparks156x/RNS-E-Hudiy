import { createContext, useContext, useId, useState } from 'react';
import config from '../data/control-defaults.json';
import './rnse-faceplate.css';
import { createFaceplateControls } from './rnseControlModel';

// Physical positions follow the Audi RNS-E quick reference; actions come from
// this fork's config.json. This is an explainer, never an input to a vehicle.
const controls = createFaceplateControls(config.input_mappings.mmi);

const ControlContext = createContext(null);
function Button({ id, className = '', children, label }) {
  const { selected, detailId, setSelected } = useContext(ControlContext);
  return <button type="button" className={`rnse-button ${className}`} aria-label={label || controls[id].title}
    aria-pressed={selected === id} aria-controls={detailId} onClick={() => setSelected(id)}>{children}</button>;
}

export default function RnseFaceplate() {
  const [selected, setSelected] = useState('knob');
  const detailId = useId();
  const selectedControl = controls[selected];
  return <ControlContext.Provider value={{ selected, detailId, setSelected }}><div className="rnse-explainer">
    <div className="rnse-explainer-heading"><span>RNS-E FACEPLATE</span><span>Select a control to see its defaults</span></div>
    <div className="rnse-faceplate" role="group" aria-label="Interactive RNS-E faceplate control guide">
      <div className="rnse-brand" aria-hidden="true">Audi Navigation <strong>plus</strong></div>
      <div className="rnse-screen" aria-hidden="true"><img src="./media/dataview-engine.jpg" alt=""/></div>
      <div className="rnse-track-buttons"><Button id="previous" label="Previous-track button">◀◀</Button><Button id="next" label="Next-track button">▶▶</Button></div>
      <div className="rnse-navigation-ring">
        <Button id="upperLeft" className="rnse-quadrant rnse-upper-left">↖</Button>
        <Button id="upperRight" className="rnse-quadrant rnse-upper-right">↗</Button>
        <Button id="lowerLeft" className="rnse-quadrant rnse-lower-left">↙</Button>
        <Button id="lowerRight" className="rnse-quadrant rnse-lower-right">↘</Button>
        <Button id="knob" className="rnse-navigation-knob"><span aria-hidden="true"/></Button>
      </div>
      <Button id="return" className="rnse-return">RETURN</Button>
      <Button id="volume" className="rnse-volume"><span aria-hidden="true">⏻</span></Button>
      <div className="rnse-function-buttons">{[
        ['radio','RADIO'], ['media','MEDIA'], ['name','NAME'], ['tel','TEL'],
        ['nav','NAV'], ['info','INFO'], ['car','CAR'], ['setup','SETUP'],
      ].map(([id, label]) => <Button key={id} id={id}>{label}</Button>)}</div>
    </div>
    <div id={detailId} className="rnse-control-detail" aria-live="polite" aria-atomic="true">
      <div className="rnse-control-title"><h3>{selectedControl.title}</h3><span>{selectedControl.stock ? 'Factory control' : 'Pi mapping'}</span></div>
      <dl>{selectedControl.actions.map(([gesture, action, key]) => <div key={gesture}><dt>{gesture}</dt><dd>{action}{key && <code>{key}</code>}</dd></div>)}</dl>
      {selectedControl.note && <p>{selectedControl.note}</p>}
    </div>
    <p className="rnse-caption">Illustrated RNS-E faceplate; some units label MEDIA as CD/TV or CD/SD. These are this fork’s bundled defaults. Your imported config can change them. Hold thresholds count repeated CAN messages; extended shell commands also require <code>features.system_actions</code>.</p>
    <a className="source-link" href="https://www.manualslib.com/manual/11574/Audi-Gps-Receiver.html" target="_blank" rel="noreferrer">Audi’s faceplate reference ↗</a>
    <a className="source-link" href="https://github.com/wiboma/hudiy#key-bindings" target="_blank" rel="noreferrer">Hudiy key bindings ↗</a>
  </div></ControlContext.Provider>;
}
