import { useEffect, useRef, useState } from 'react';
import type { ManagementApi } from './ManagementApp';
import { managementRequest } from './managementModel';
import { LatestVideoWriter, sameVideoSettings, VIDEO_DEFAULTS, VIDEO_FIELDS, VideoSettings, VideoSnapshot, videoNumber } from './videoModel';
import './videoPanel.css';

interface Props { api?: ManagementApi; pin?: string; }
type Apply = { settings: VideoSettings; output: string | null; pin: string };
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The video request failed.';
const headers = (pin: string) => ({ 'Content-Type': 'application/json', 'X-Hudiy-Management': '1', ...(pin ? { 'X-Hudiy-Pin': pin } : {}) });

export function VideoPanel({ api = managementRequest, pin = '' }: Props) {
  const [snapshot, setSnapshot] = useState<VideoSnapshot | null>(null);
  const [draft, setDraft] = useState<VideoSettings>({ ...VIDEO_DEFAULTS });
  const [output, setOutput] = useState('');
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState(0);
  const [pending, setPending] = useState(false);
  const [action, setAction] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const current = useRef(0);
  const alive = useRef(true);
  const writer = useRef<LatestVideoWriter<Apply, VideoSnapshot> | null>(null);
  useEffect(() => {
    alive.current = true;
    const queue = new LatestVideoWriter<Apply, VideoSnapshot>(value => api<VideoSnapshot>('/video/apply', { method: 'POST', headers: headers(value.pin), body: JSON.stringify({ settings: value.settings, output: value.output }) }), (ticket, result, reason) => {
      if (!alive.current) return;
      // Keep the last confirmed compositor state, even when the user has a newer
      // draft. A later failed request must not make that earlier apply disappear.
      if (result) setSnapshot(result);
      if (ticket !== current.current) return;
      setPending(false);
      if (reason) {
        setError(errorText(reason));
        // A compositor can disappear between applying and replying. Refresh
        // confirmed availability without overwriting a newer slider draft.
        void api<VideoSnapshot>('/video').then(state => { if (alive.current && ticket === current.current) setSnapshot(state); }).catch(() => undefined);
        return;
      }
      if (result) { setError(''); setMessage(result.active ? 'Applied to the display. Save for startup to keep these values.' : result.error || 'The compositor did not apply these values.'); }
    });
    writer.current = queue;
    let mounted = true;
    setLoading(true);
    void api<VideoSnapshot>('/video').then(result => {
      if (!mounted) return;
      setSnapshot(result); setDraft({ ...(result.active ? result.settings : result.saved_profile?.settings || VIDEO_DEFAULTS) });
      setOutput(result.output || result.saved_profile?.output || (result.outputs.length === 1 ? result.outputs[0].output : ''));
      setError(result.error || '');
    }).catch(reason => { if (mounted) setError(errorText(reason)); }).finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; alive.current = false; queue.close(); writer.current = null; };
  }, [api]);
  useEffect(() => {
    if (!edit) return undefined;
    const ticket = edit;
    const timer = window.setTimeout(() => writer.current?.submit({ settings: { ...draft }, output: output || null, pin }, ticket), 250);
    return () => window.clearTimeout(timer);
  }, [edit, draft, output, pin]);
  const change = (values: VideoSettings, selectedOutput = output) => {
    const ticket = ++current.current; setDraft(values); setOutput(selectedOutput); setEdit(ticket); setPending(true); setError(''); setMessage('');
  };
  const refresh = async () => {
    const ticket = current.current;
    setLoading(true); setError('');
    try {
      const result = await api<VideoSnapshot>('/video');
      if (!alive.current || ticket !== current.current) return;
      setSnapshot(result); setError(result.error || '');
      if (!output && result.outputs.length === 1) setOutput(result.outputs[0].output);
    } catch (reason) { if (alive.current && ticket === current.current) setError(errorText(reason)); }
    finally { if (alive.current) setLoading(false); }
  };
  const perform = async (kind: 'profile' | 'reset') => {
    const ticket = current.current;
    setAction(kind); setError(''); setMessage('');
    try {
      const result = await api<VideoSnapshot>(`/video/${kind}`, { method: 'POST', headers: headers(pin), body: JSON.stringify(kind === 'profile' ? { settings: draft, output: output || null } : {}) });
      if (!alive.current) return;
      setSnapshot(result);
      if (kind === 'reset') { setDraft({ ...VIDEO_DEFAULTS }); setEdit(0); current.current = 0; setMessage('Original compositor colors restored. Saved startup adjustment removed.'); }
      else setMessage('Saved for startup. These values are separate from config.json.');
    } catch (reason) {
      if (alive.current) setError(errorText(reason));
      // Reset can restore the output even when removing the startup file fails.
      // Read back the native state rather than keeping a stale active badge.
      try {
        const result = await api<VideoSnapshot>('/video');
        if (alive.current && current.current === ticket) setSnapshot(result);
      } catch { /* Keep the actionable error if status is also unavailable. */ }
    }
    finally { if (alive.current) setAction(''); }
  };
  const available = !!snapshot?.available;
  const selectable = available && (!!snapshot?.outputs.some(item => item.output === output) || (!output && snapshot?.outputs.length === 1));
  const busy = !!action || loading;
  const applied = !!snapshot?.active && snapshot.output === (output || null) && sameVideoSettings(snapshot.settings, draft);
  return <section className="manager-video" aria-label="Pi video">
    <div className="manager-video-heading"><div><h2>Pi video</h2><p>Adjust the Pi’s display colors live. Save separately for startup.</p></div><div className="manager-video-state"><span className={`manager-video-status ${applied ? 'active' : ''}`} aria-live="polite">{loading ? 'Checking display…' : pending ? 'Applying…' : !available ? 'Unavailable' : edit && !applied ? 'Values not applied' : snapshot?.active ? 'Live adjustment' : 'Original colors'}</span><button type="button" disabled={busy || pending} onClick={() => void refresh()}>Refresh display</button></div></div>
    {snapshot && (snapshot.outputs.length === 1 && output === snapshot.outputs[0].output ? <p className="manager-video-single-output">Display · {snapshot.outputs[0].name || output}{snapshot.outputs[0].description ? ` · ${snapshot.outputs[0].description}` : ''}</p> : <label className="manager-video-output">Display<select aria-label="Video output" value={output} disabled={!available || busy || pending} onChange={event => change({ ...draft }, event.target.value)}><option value="" disabled>Choose a display</option>{snapshot.outputs.map(item => <option key={item.output} value={item.output}>{item.name || item.output}{item.description ? ` · ${item.description}` : ''}</option>)}</select></label>)}
    {error && <p className="manager-inline-error" role="alert">{error}</p>}
    {!loading && !available && <p className="manager-video-unavailable">Video controls need the Pi’s Wayland session and a compositor that supports gamma control.</p>}
    <div className="manager-video-controls">{VIDEO_FIELDS.map(field => <div className="manager-video-control" key={field.key}><div className="manager-video-control-label"><label htmlFor={`video-${field.key}`}>{field.label}</label><output htmlFor={`video-${field.key}`}>{videoNumber(field.key, draft[field.key])}</output></div><input id={`video-${field.key}`} type="range" min={field.min} max={field.max} step={field.step} value={draft[field.key]} disabled={!selectable || busy} aria-label={field.label} onChange={event => change({ ...draft, [field.key]: Number(event.target.value) })} /><p>{field.help}</p></div>)}</div>
    <details className="manager-video-compact-help"><summary>What the controls do</summary>{VIDEO_FIELDS.map(field => <p key={field.key}><strong>{field.label}:</strong> {field.help}</p>)}</details>
    <div className="manager-video-test-strip" role="img" aria-label="Black-to-white and red, green, blue reference patches"><div className="manager-video-grays">{['#000', '#111', '#333', '#666', '#999', '#ccc', '#eee', '#fff'].map(color => <span key={color} style={{ background: color }} />)}</div><div className="manager-video-rgb">{['#f00', '#0f0', '#00f'].map(color => <span key={color} style={{ background: color }} />)}</div></div>
    <div className="manager-video-actions"><button type="button" disabled={!selectable || busy} onClick={() => change({ ...VIDEO_DEFAULTS })}>Neutral values</button><button type="button" disabled={busy || pending || (!snapshot?.active && !snapshot?.saved_profile && !snapshot?.profile_error)} onClick={() => void perform('reset')}>Restore original</button><button type="button" className="manager-primary" disabled={!selectable || busy || pending || !applied} onClick={() => void perform('profile')}>{action === 'profile' ? 'Saving…' : 'Save for startup'}</button></div>
    <p className="manager-video-note" aria-live="polite">{message || (snapshot?.saved_profile ? 'A startup adjustment is saved. Restore original also removes it.' : 'Live changes last until Manager stops or the Pi restarts. Restore original releases control back to the compositor.')}</p>
  </section>;
}
