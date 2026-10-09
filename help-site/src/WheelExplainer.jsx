import React, { useId, useState } from 'react';
import './wheel-explainer.css';

const readings = [
  { id: 'normal', label: 'Normal', image: 'wheel-readings-normal.png', title: 'Readings without taking over the wheel', gesture: 'Leave the wheel in its normal mode.', result: 'Values keep updating. The navigation wheel keeps its usual Hudiy controls; nothing in this DIS page is selected.', icon: null },
  { id: 'page', label: 'Wheel mode', image: 'wheel-readings-page.png', title: 'The icon means the DIS owns the wheel', gesture: 'Double-click MODE while this page is visible.', result: 'The wheel icon appears at the top right. The light background on Daily is the current selection. Rotate the navigation wheel to move between the page name and recording actions.', icon: [116, 0] },
  { id: 'browse', label: 'Choose page', image: 'wheel-readings-browse.png', title: 'Rotate through your DIS pages', gesture: 'Select the page name, click the wheel, then rotate.', result: 'The name and values change together as you browse. Here, Engine is the next page. Click to keep it; double-click the wheel to cancel and return to the original page.', icon: [116, 0] },
  { id: 'start', label: 'Start', image: 'wheel-readings-start.png', title: 'Start the page’s recording profile', gesture: 'With page browsing finished, rotate to the play symbol and click.', result: 'The play symbol starts the shared recorder using the profile linked to this DIS page. The selection moves between actions, not between individual readings.', icon: [116, 0] },
  { id: 'stop', label: 'Stop', image: 'wheel-readings-stop.png', title: 'The play symbol becomes Stop', gesture: 'While recording, rotate to the square and click to stop.', result: 'A small recording indicator lights beside the page name. The square replaces Play, and the flag is available beside it while recording. Click the square to finish the session.', icon: [116, 0] },
  { id: 'mark', label: 'Marker', image: 'wheel-readings-mark.png', title: 'Mark a moment without stopping', gesture: 'While recording, rotate to the flag and click.', result: 'Adds a marker named for the current DIS page. Recording continues. You can find the marker later in the recording’s Review screen.', icon: [116, 0] },
];
const phone = [
  { id: 'normal', label: 'Normal', image: 'wheel-phone-normal.png', title: 'A call can be visible without wheel control', gesture: 'Keep normal wheel mode.', result: 'The caller and available actions are shown, but no action is highlighted. The wheel still controls Hudiy.', icon: null },
  { id: 'accept', label: 'Accept', image: 'wheel-phone-accept.png', title: 'The wheel icon marks call control', gesture: 'Double-click MODE to take control; rotate up to select Accept.', result: 'The icon appears before the call status. The arrow and light background identify the selected action. Click the navigation wheel to accept the call.', icon: [3, 2] },
  { id: 'reject', label: 'Reject', image: 'wheel-phone-reject.png', title: 'Rotate down to choose Reject', gesture: 'Rotate down, then click the navigation wheel.', result: 'The highlight moves from Accept to Reject. Clicking sends the reject action to Hudiy; rotating alone does not answer or reject anything.', icon: [3, 2] },
  { id: 'end', label: 'In a call', image: 'wheel-phone-end.png', title: 'An active call has one action', gesture: 'Click the navigation wheel while End Call is highlighted.', result: 'Ends the active call. There is no Accept / Reject selection to scroll through in this state.', icon: [15, 2] },
];

export function WheelExplainer({ mode = 'readings' }) {
  const states = mode === 'phone' ? phone : readings;
  const [selected, setSelected] = useState(1);
  const panelId = useId();
  const current = states[selected] || states[1];
  return <div className="wheel-explainer">
    <div className="wheel-state-picker" aria-label={mode === 'phone' ? 'Phone wheel-control examples' : 'Readings wheel-control examples'}>
      {states.map((state, i) => <button key={state.id} type="button" aria-pressed={current.id === state.id} aria-controls={panelId} onClick={() => setSelected(i)}>{state.label}</button>)}
    </div>
    <div className="wheel-example" id={panelId}>
      <figure className="wheel-example-figure">
        <div className="wheel-screen-surround">
          <div className="wheel-screen">
            <img src={`./media/${current.image}`} alt={`${current.title}. ${current.icon ? 'Wheel ownership icon visible.' : 'No wheel ownership icon.'}`} loading="lazy" width="512" height="384"/>
            {current.icon && <span className="wheel-icon-halo" aria-hidden="true" style={{ left: `${current.icon[0] / 128 * 100 - 1.5}%`, top: `${current.icon[1] / 96 * 100 - 1.5}%` }}/>}</div>
        </div>
        <figcaption><span className={`wheel-ownership-dot ${current.icon ? 'active' : ''}`} aria-hidden="true"/>{current.icon ? 'Circled icon: navigation wheel controls this DIS page.' : 'No wheel icon: navigation wheel keeps its normal controls.'}</figcaption>
      </figure>
      <div className="wheel-example-description" aria-live="polite" aria-atomic="true">
        <h3>{current.title}</h3>
        <dl><dt>On the wheel</dt><dd>{current.gesture}</dd><dt>On the display</dt><dd>{current.result}</dd></dl>
        <p className="wheel-return">Double-click MODE again to give the wheel back to Hudiy. The volume wheel keeps its usual function.</p>
      </div>
    </div>
    {mode === 'phone' && <p className="wheel-auto-phone">With <code>display.phone.scroll_wheel_phone_menu</code> enabled, a live call can take wheel control automatically. If you switch back to normal mode, it stays there for that call. Explicit control of a readings page takes priority.</p>}
  </div>;
}

export default WheelExplainer;
