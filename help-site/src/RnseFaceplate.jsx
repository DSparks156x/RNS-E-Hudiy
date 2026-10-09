import { createContext, useContext, useId, useState } from 'react';
import config from '../data/control-defaults.json';
import './rnse-faceplate.css';

// Physical positions follow the Audi RNS-E quick reference; actions come from
// this fork's config.json. This is an explainer, never an input to a vehicle.
const mmi = config.input_mappings.mmi;
const hudiyKeys = {
  KEY_V: 'Previous media', KEY_N: 'Next media', KEY_UP: 'Move focus up',
  KEY_DOWN: 'Move focus down', KEY_LEFT: 'Move left', KEY_RIGHT: 'Move right',
  KEY_ENTER: 'Select / confirm', KEY_ESC: 'Go back', KEY_H: 'Hudiy home',
  KEY_M: 'Projection voice assistant', KEY_1: 'Scroll left', KEY_2: 'Scroll right',
};
const normal = key => key ? hudiyKeys[key] || `Sends ${key}` : 'No Pi action';
const mapped = (pattern, title, extra = {}) => ({
  title, pattern,
  actions: [
    ['Press', normal(mmi.short_press[pattern]), mmi.short_press[pattern]],
    ['Hold', normal(mmi.long_press[pattern]), mmi.long_press[pattern]],
    ...(mmi.extended_press[pattern] ? [['Extended hold',
      { '1,0': 'Save support logs', '2,0': 'Shut down the Pi', '0,16': 'Reboot the Pi' }[pattern], null]] : []),
  ], ...extra,
});
const stock = title => ({ title, actions: [['RNS-E', 'Factory function; no Pi key mapping in this config.']], stock: true });
const controls = {
  previous: mapped('1,0', 'Previous-track button'),
  next: mapped('2,0', 'Next-track button'),
  upperLeft: mapped('64,0', 'Upper-left control button'),
  lowerLeft: mapped('128,0', 'Lower-left control button'),
  upperRight: stock('Upper-right control button'),
  lowerRight: stock('Lower-right control button'),
  knob: { title: 'Navigation knob', actions: [
    ['Turn left', normal(mmi.short_press['0,32']), mmi.short_press['0,32']],
    ['Turn right', normal(mmi.short_press['0,64']), mmi.short_press['0,64']],
    ['Press', normal(mmi.short_press['0,16']), mmi.short_press['0,16']],
    ['Hold', normal(mmi.long_press['0,16']), mmi.long_press['0,16']],
    ['Extended hold', 'Reboot the Pi'],
  ] },
  return: mapped('0,2', 'RETURN', { note: 'The longer hold sends KEY_0. Hudiy does not document a standard action for that key.' }),
  setup: mapped('0,1', 'SETUP'),
  volume: { title: 'Power / volume knob', actions: [['RNS-E', 'Adjusts the head unit’s volume and power. No Pi key mapping in this config.']], stock: true },
  radio: stock('RADIO'), media: stock('CD/TV'), name: stock('NAME'),
  tel: stock('TEL'), nav: stock('NAV'), info: stock('INFO'), car: stock('CAR'),
};

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
        ['radio','RADIO'], ['media','CD/TV'], ['name','NAME'], ['tel','TEL'],
        ['nav','NAV'], ['info','INFO'], ['car','CAR'], ['setup','SETUP'],
      ].map(([id, label]) => <Button key={id} id={id}>{label}</Button>)}</div>
    </div>
    <div id={detailId} className="rnse-control-detail" aria-live="polite" aria-atomic="true">
      <div className="rnse-control-title"><h3>{selectedControl.title}</h3><span>{selectedControl.stock ? 'Factory control' : 'Pi mapping'}</span></div>
      <dl>{selectedControl.actions.map(([gesture, action, key]) => <div key={gesture}><dt>{gesture}</dt><dd>{action}{key && <code>{key}</code>}</dd></div>)}</dl>
      {selectedControl.note && <p>{selectedControl.note}</p>}
    </div>
    <p className="rnse-caption">Illustrated CD/TV faceplate; some units label this button MEDIA or CD/SD. These are this fork’s bundled defaults. Your imported config can change them. Hold thresholds count repeated CAN messages; extended system actions also require <code>features.system_actions</code>.</p>
    <a className="source-link" href="https://www.manualslib.com/manual/11574/Audi-Gps-Receiver.html" target="_blank" rel="noreferrer">Audi’s faceplate reference ↗</a>
    <a className="source-link" href="https://github.com/wiboma/hudiy#key-bindings" target="_blank" rel="noreferrer">Hudiy key bindings ↗</a>
  </div></ControlContext.Provider>;
}
