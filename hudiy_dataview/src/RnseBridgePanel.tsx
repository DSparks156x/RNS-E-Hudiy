import { useCallback, useEffect, useRef, useState } from 'react';
import type { ManagementApi } from './ManagementApp';
import { displayValue, RNSE_DEFAULTS, SettingField, JsonValue } from './managementModel';
import { lcdLabel, ReleasedValue, RnseChannel, RnseControlSnapshot, sourceLabel } from './rnseBridgeModel';
import './rnseBridgePanel.css';

interface Props { view: 'live' | 'automatic'; fields: SettingField[]; edits: Record<string, string>; disabled: boolean; pin?: string; api: ManagementApi; set: (id: string, value: string) => void; }
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : 'RNS-E control is unavailable.';
const headers = (pin: string) => ({ 'Content-Type': 'application/json', 'X-Hudiy-Management': '1', ...(pin ? { 'X-Hudiy-Pin': pin } : {}) });

function LiveSlider({ channel, label, value, syncToken, disabled, commit }: { channel: RnseChannel; label: string; value: number; syncToken: unknown; disabled: boolean; commit: (value: number) => void }) {
  const [draft, setDraft] = useState(value);
  const values = useRef(new ReleasedValue(value));
  const gesturing = useRef(false);
  useEffect(() => { if (!gesturing.current) { values.current.sync(value); setDraft(value); } }, [value, syncToken]);
  const max = channel === 'brightness' ? 10 : 100;
  const change = (next: number) => { values.current.change(next); setDraft(next); };
  const release = () => { gesturing.current = false; const next = values.current.release(); if (next !== null) commit(next); };
  const step = (delta: number) => { change(Math.max(0, Math.min(max, draft + delta))); release(); };
  return <div className="rnse-live-control"><div className="rnse-control-title"><label htmlFor={`rnse-live-${channel}`}>{label}</label><output htmlFor={`rnse-live-${channel}`}>{channel === 'brightness' ? `${draft} / 10` : lcdLabel(draft)}</output></div>
    <div className="rnse-live-slider"><button type="button" disabled={disabled || draft <= 0} aria-label={`Decrease ${label}`} onClick={() => step(-1)}>−</button><input id={`rnse-live-${channel}`} type="range" min="0" max={max} step="1" value={draft} disabled={disabled} aria-label={label} onPointerDown={event => { gesturing.current = true; event.currentTarget.setPointerCapture(event.pointerId); }} onChange={event => change(Number(event.target.value))} onPointerUp={release} onPointerCancel={() => { gesturing.current = false; setDraft(values.current.cancel()); }} onKeyDown={() => { gesturing.current = true; }} onKeyUp={release} onBlur={release} /><button type="button" disabled={disabled || draft >= max} aria-label={`Increase ${label}`} onClick={() => step(1)}>+</button></div>
    <small>{channel === 'brightness' ? 'RNS-E brightness dial' : '0 follows the cluster. 1–5 use the stock minimum of 6.'}</small>
  </div>;
}

export function RnseBridgePanel({ view, fields, edits, disabled, pin = '', api, set }: Props) {
  const [snapshot, setSnapshot] = useState<RnseControlSnapshot | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [reachable, setReachable] = useState(false);
  const [syncVersion, setSyncVersion] = useState(0);
  const alive = useRef(false), writing = useRef(false);
  const writeEpoch = useRef(0);
  const field = (path: string) => fields.find(item => item.path === path);
  const text = (item: SettingField) => edits[item.id] ?? displayValue(item.value, item.metadata);
  const refresh = useCallback(async (preserveError = false) => {
    const epoch = writeEpoch.current;
    try { const next = await api<RnseControlSnapshot>('/rnse-control'); if (alive.current && !writing.current && epoch === writeEpoch.current) { setSnapshot(next); setReachable(true); if (!preserveError || next.error) setError(next.error || ''); } }
    catch (reason) { if (alive.current && epoch === writeEpoch.current && !writing.current) { setError(errorText(reason)); setReachable(false); } }
    finally { if (alive.current) setLoading(false); }
  }, [api]);
  useEffect(() => { alive.current = true; void refresh(); const timer = window.setInterval(() => { if (!writing.current) void refresh(true); }, 3000); return () => { alive.current = false; window.clearInterval(timer); }; }, [refresh]);
  const manual = async (channel: RnseChannel, value: number) => {
    if (writing.current) return;
    writing.current = true; writeEpoch.current++; setPending(true); setError('');
    try { const result = await api<RnseControlSnapshot>('/rnse-control/manual', { method: 'POST', headers: headers(pin), body: JSON.stringify({ [channel]: value }) }); if (alive.current) { setSnapshot(result); setError(result.error || ''); } }
    catch (reason) { if (alive.current) setError(errorText(reason)); }
    finally { writing.current = false; if (alive.current) { setPending(false); setSyncVersion(previous => previous + 1); void refresh(true); } }
  };
  const unavailable = !reachable || !snapshot || snapshot.protocol_available === false || ['unavailable', 'disconnected', 'stopped', 'error', 'protocol_unavailable', 'waiting_protocol', 'invalid_brightness'].includes(snapshot.state);
  const busy = disabled || pending || loading || unavailable;
  const toggle = (path: string, label: string) => {
    const item = field(path); if (!item) return null;
    const enabled = text(item) === 'true';
    return <button type="button" className={`manager-switch ${enabled ? 'on' : ''}`} role="switch" aria-label={label} aria-checked={enabled} disabled={disabled} onClick={() => set(item.id, String(!enabled))}><span />{enabled ? 'On' : 'Off'}</button>;
  };
  const stepper = (path: string, label: string, max: number, shortLabel = label) => {
    const item = field(path); if (!item) return null;
    const value = Number(text(item));
    if (!Number.isInteger(value) || value < 0 || value > max || !text(item).trim()) {
      const fallback = path.split('.').slice(1).reduce<JsonValue>((node, key) => node && typeof node === 'object' && !Array.isArray(node) ? node[key] : null, RNSE_DEFAULTS);
      return <div className="rnse-config-value"><label>{shortLabel}</label><div className="manager-stepper"><output>Unset</output><button type="button" disabled={disabled} aria-label={`Set default ${label}`} onClick={() => set(item.id, String(fallback))}>Set</button></div></div>;
    }
    return <div className="rnse-config-value"><label>{shortLabel}</label><div className="manager-stepper" role="group" aria-label={label}><button type="button" aria-label={`Decrease ${label}`} disabled={disabled || value <= 0} onClick={() => set(item.id, String(Math.max(0, value - 1)))}>−</button><output className={max === 100 && value === 0 ? 'rnse-cluster-value' : undefined}>{max === 100 && value === 0 ? 'Cluster' : value}<small>{max === 100 && value === 0 ? '' : `/ ${max}`}</small></output><button type="button" aria-label={`Increase ${label}`} disabled={disabled || value >= max} onClick={() => set(item.id, String(Math.min(max, value + 1)))}>+</button></div></div>;
  };
  const state = loading ? 'Checking bridge…' : pending ? 'Requesting…' : unavailable ? 'Unavailable' : snapshot?.inhibited || snapshot?.state === 'inhibited' ? 'Sending paused' : snapshot?.state === 'waiting_vehicle_state' ? 'Waiting for lights state' : ['waiting', 'waiting_radio'].includes(snapshot?.state || '') ? 'Waiting for RNS-E' : snapshot?.queued ? 'Queued once' : 'Bridge ready';
  return <section className={`rnse-bridge rnse-bridge-${view}`} aria-label={view === 'live' ? 'RNS-E live controls' : 'RNS-E automatic settings'}>
    {view === 'live' && <><div className="rnse-bridge-heading"><span>Source · {snapshot ? sourceLabel(snapshot.source) : '—'}</span><div className="rnse-bridge-state"><span aria-live="polite">{state}</span><button type="button" disabled={pending || loading} onClick={() => void refresh()}>Refresh</button></div></div>
    {error && <p className="manager-inline-error" role="alert">{error}</p>}
    <div className="rnse-live-controls"><LiveSlider channel="brightness" label="Brightness dial" value={snapshot?.manual_overrides.brightness ?? snapshot?.level ?? 10} syncToken={`${syncVersion}:${JSON.stringify(snapshot)}`} disabled={busy} commit={value => void manual('brightness', value)} /><LiveSlider channel="lcd_brightness" label="LCD / cluster dimming" value={snapshot?.manual_overrides.lcd_brightness ?? snapshot?.lcd_brightness ?? 0} syncToken={`${syncVersion}:${JSON.stringify(snapshot)}`} disabled={busy} commit={value => void manual('lcd_brightness', value)} /></div>
    <p className="rnse-live-note">Temporary tests · sent once on release. Next day/night change or Apply restores configured behavior.</p></>}
    {view === 'automatic' && <><div className="rnse-auto-controls">{[{ prefix: 'rnse.auto_brightness', title: 'Brightness dial', max: 10 }, { prefix: 'rnse.auto_lcd_brightness', title: 'LCD dimming', max: 100 }].map(group => <section className="rnse-auto-card" key={group.prefix}><div className="rnse-auto-heading"><h3>{group.title}</h3>{toggle(`${group.prefix}.enabled`, `Automatic ${group.title}`)}</div><div className="rnse-auto-levels">{stepper(`${group.prefix}.day_brightness`, `Automatic ${group.title} · day`, group.max, 'Day')}{stepper(`${group.prefix}.night_brightness`, `Automatic ${group.title} · night`, group.max, 'Night')}</div></section>)}</div>
    <div className="rnse-source-setting"><div><h3>Source label</h3><small>From Hudiy’s reported media/navigation provider; connection is inferred.</small></div>{toggle('rnse.source_label.enabled', 'Source label')}</div>
    <details className="rnse-startup-settings"><summary>Values when automatic is off</summary><div className="rnse-auto-levels">{stepper('rnse.manual_brightness', 'Configured brightness dial', 10)}{stepper('rnse.manual_lcd_brightness', 'Configured LCD dimming', 100)}</div><p>These are the saved values used when each automatic mode is off. Apply saves them; the live sliders above are temporary tests.</p></details>
    <details className="rnse-bridge-help"><summary>Brightness help</summary><p>The brightness dial runs from 0 to 10. LCD dimming runs from 1 to 100, or 0 to follow the original cluster signal. LCD levels 1–5 all use the stock minimum of 6.</p><p>Automatic modes choose the saved day or night level from the vehicle’s lights state. Enable and day/night edits are configuration drafts until you press Apply.</p><p>The bridge queues each changed setting once. Waiting means it cannot queue the request yet. Queued does not confirm the screen changed. Pi video colors and Hudiy’s theme are separate.</p>{snapshot?.source_evidence != null && <p>Source evidence: {typeof snapshot.source_evidence === 'string' ? snapshot.source_evidence : JSON.stringify(snapshot.source_evidence)}</p>}</details></>}
  </section>;
}
