import { CSSProperties, useCallback, useEffect, useRef, useState } from 'react';
import { useHudiyTheme } from '../hooks/useHudiyTheme';
import { installHudiyKeyNav } from '../hudiyKeyNav';
import { installManagerPointerScroll } from '../managerPointerScroll';
import { canSummary, chainSummary, FirmwareFile, flashTargets, formatSetting, Job, request, sameValues, SettingField, SettingsSnapshot, SettingValues, Status } from './avsdModel';
import './avsd.css';

const TABS = ['status', 'settings', 'logs', 'update'] as const;
type Tab = typeof TABS[number];
const TAB_LABEL: Record<Tab, string> = { status: 'Status', settings: 'Settings', logs: 'Logs', update: 'Update' };
const LOG_SOURCES = [['live', 'Link'], ['enc', 'Encoder'], ['cap', 'Capture'], ['supervisor', 'Supervisor']] as const;

interface Confirm { title: string; body: string; action: string; run: () => void; }

/** Puts the knob's highlight in a dialog that opened after a request, not on a press. hudiyKeyNav listens for this event. */
function useDialogHighlight(open: boolean) {
  useEffect(() => { window.dispatchEvent(new Event('hudiy-attached')); }, [open]);
}

export function AvsdApp() {
  const { theme } = useHudiyTheme(null);
  const root = useRef<HTMLDivElement>(null);
  const opensUpdate = new URLSearchParams(window.location.search).has('update');
  const [tab, setTab] = useState<Tab>(opensUpdate ? 'update' : 'status');
  const [status, setStatus] = useState<Status | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [message, setMessage] = useState('');
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const askedUpdate = useRef(false);
  useDialogHighlight(Boolean(confirm));

  useEffect(() => root.current ? installManagerPointerScroll(root.current) : undefined, []);
  useEffect(() => root.current && window.hudiy ? installHudiyKeyNav({
    root: root.current,
    hudiy: window.hudiy,
    activeTab: '.avsd-tabs button.active',
    onTab: delta => setTab(current => TABS[Math.max(0, Math.min(TABS.length - 1, TABS.indexOf(current) + delta))]),
  }) : undefined, []);

  const refreshStatus = useCallback(() => request<Status>('/api/status').then(setStatus).catch(() => undefined), []);
  const refreshJob = useCallback(() => request<{ job: Job | null }>('/api/job').then(data => setJob(data.job)).catch(() => undefined), []);
  useEffect(() => {
    void refreshStatus(); void refreshJob();
    const slow = window.setInterval(() => void refreshStatus(), 3000);
    const fast = window.setInterval(() => void refreshJob(), 1000);
    return () => { window.clearInterval(slow); window.clearInterval(fast); };
  }, [refreshStatus, refreshJob]);
  useEffect(() => {
    if (!message) return undefined;
    const timer = window.setTimeout(() => setMessage(''), 8000);
    return () => window.clearTimeout(timer);
  }, [message]);

  const act = useCallback(async (path: string, body: unknown = {}) => {
    try {
      const result = await request<unknown>(path, body);
      void refreshStatus(); void refreshJob();
      return result;
    } catch (error) {
      setMessage((error as Error).message);
      return null;
    }
  }, [refreshJob, refreshStatus]);

  const askUpdate = useCallback(() => setConfirm({
    title: 'Update A/V over SD?',
    body: 'Hudiy quits and the hotspot goes down so the Pi can join your phone hotspot or home Wi-Fi. It waits for internet, updates and reboots.',
    action: 'Update now',
    run: () => void act('/api/update'),
  }), [act]);
  useEffect(() => {
    if (opensUpdate && status?.can_change && !askedUpdate.current) {
      askedUpdate.current = true;
      askUpdate();
    }
  }, [askUpdate, opensUpdate, status?.can_change]);

  const running = job?.state === 'running';
  const readOnly = status ? !status.can_change : true;
  const locked = readOnly || running;
  const themeVars = Object.fromEntries(Object.entries(theme).filter(([, value]) => typeof value === 'string')
    .map(([key, value]) => [`--${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`, value]));

  return <div ref={root} className="avsd" style={themeVars as CSSProperties}>
    <nav className="avsd-tabs">
      {TABS.map(name => <button key={name} className={tab === name ? 'active' : ''} onClick={() => setTab(name)}>{TAB_LABEL[name]}</button>)}
    </nav>
    {readOnly && status && <p className="avsd-note avsd-banner">Watching only. Change things from the car.</p>}
    {message && <p className="avsd-toast" role="alert">{message}</p>}
    <main className="avsd-page">
      {!status && <p className="avsd-note">Loading…</p>}
      {status && tab === 'status' && <StatusPage status={status} locked={locked} act={act} />}
      {tab === 'settings' && <SettingsPage locked={locked} act={act} />}
      {tab === 'logs' && <LogsPage portal={status?.portal || []} />}
      {status && tab === 'update' && <UpdatePage status={status} job={job} locked={locked} act={act} setConfirm={setConfirm} />}
    </main>
    {confirm && <div className="avsd-dialog-back"><div className="avsd-dialog" role="dialog" aria-modal="true">
      <h2>{confirm.title}</h2>
      <p>{confirm.body}</p>
      <div className="avsd-row">
        <button data-key-back onClick={() => setConfirm(null)}>Cancel</button>
        <button className="danger" onClick={() => { const run = confirm.run; setConfirm(null); run(); }}>{confirm.action}</button>
      </div>
    </div></div>}
  </div>;
}

type Act = (path: string, body?: unknown) => Promise<unknown>;

function StatusPage({ status, locked, act }: { status: Status; locked: boolean; act: Act }) {
  const { chain } = status;
  const summary = chainSummary(chain);
  const [counters, setCounters] = useState<{ valid: boolean; counters: Record<string, number> } | null>(null);
  const rows: [string, string | number][] = [
    ['Frames', chain.stat.frames ?? '–'], ['Dropped', chain.stat.drop ?? '–'], ['Key requests', chain.stat.keyreq ?? '–'],
    ['Served', chain.stat.served ?? '–'], ['Encoder over limit', chain.encoder_over], ['CAN', canSummary(status.can)],
    ['Teensy', status.teensy.present ? 'On USB' : 'Not on USB'],
  ];
  const canRead = !locked && status.can.up && !status.can.listen_only;
  return <>
    <h1 className={`avsd-summary ${summary.tone}`}>{summary.text}</h1>
    {status.decoder.old && <p className="avsd-warning">The RNS-E decoder ({status.decoder.crc}) is too old for this encoder: no video. Flash the RNS-E on the Update page.</p>}
    <dl className="avsd-table">{rows.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
    <div className="avsd-row">
      {chain.disabled
        ? <button disabled={locked} onClick={() => void act('/api/chain', { action: 'start' })}>Start chain</button>
        : <>
            <button disabled={locked} onClick={() => void act('/api/chain', { action: 'restart' })}>Restart chain</button>
            <button disabled={locked} onClick={() => void act('/api/chain', { action: 'stop' })}>Stop chain</button>
          </>}
      <button disabled={!canRead} onClick={() => void act('/api/unit/counters').then(result => { if (result) setCounters(result as typeof counters); })}>Read RNS-E counters</button>
    </div>
    {counters && (counters.valid
      ? <dl className="avsd-table">{Object.entries(counters.counters).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
      : <p className="avsd-note">The RNS-E has no counters yet. It has not streamed since power-on.</p>)}
  </>;
}

/** Press to change, turn the knob, press to confirm. RETURN puts the old value back. */
function SettingRow({ field, value, disabled, onChange }: { field: SettingField; value: number; disabled: boolean; onChange: (value: number) => void }) {
  const id = `avsd-${field.id}`;
  return <div className="avsd-setting">
    <div className="avsd-setting-name"><label htmlFor={id}>{field.label} <span>({field.id})</span></label><small>{field.help}</small></div>
    {field.kind === 'choice'
      ? <select id={id} value={value} disabled={disabled} onChange={event => onChange(Number(event.target.value))}>
          {field.options?.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      : <div className="avsd-slider">
          <output htmlFor={id}>{formatSetting(field, value)}</output>
          <input id={id} type="range" min={field.min} max={field.max} step={field.step} value={value} disabled={disabled} onChange={event => onChange(Number(event.target.value))} />
        </div>}
  </div>;
}

function SettingsPage({ locked, act }: { locked: boolean; act: Act }) {
  const [snapshot, setSnapshot] = useState<SettingsSnapshot | null>(null);
  const [edits, setEdits] = useState<SettingValues | null>(null);
  const load = useCallback(() => request<SettingsSnapshot>('/api/settings').then(data => setSnapshot(data)).catch(() => undefined), []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 2000);
    return () => window.clearInterval(timer);
  }, [load]);
  if (!snapshot) return <p className="avsd-note">Loading…</p>;
  const values = edits || snapshot.values;
  const unapplied = !sameValues(values, snapshot.values);
  const unsaved = !sameValues(values, snapshot.saved);
  const post = (path: string, body: unknown = {}) => void act(path, body).then(result => { if (result) { setSnapshot(result as SettingsSnapshot); setEdits(null); } });
  return <div className="avsd-settings">
    <div className="avsd-settings-list">
      {snapshot.encflags_override && <p className="avsd-warning">ENCFLAGS is set in avsd.env. CYC, DITHER, SRCDEAD, SRCMEAN and FILLPEN do nothing while it is.</p>}
      {snapshot.fields.map(field => <SettingRow key={field.id} field={field} value={values[field.id]} disabled={locked} onChange={value => setEdits({ ...values, [field.id]: value })} />)}
    </div>
    <div className="avsd-row avsd-settings-actions">
      <button className="primary" disabled={locked || !unapplied} onClick={() => post('/api/settings', { values })}>Apply</button>
      <button disabled={locked || !unsaved} onClick={() => post('/api/settings/save', { values })}>Save</button>
      <button disabled={locked || (sameValues(values, snapshot.defaults) && sameValues(snapshot.saved, snapshot.defaults))} onClick={() => post('/api/settings/defaults')}>Restore defaults</button>
      <span className="avsd-settings-state">{unapplied ? 'Not applied yet' : snapshot.temporary ? 'Applied until reboot' : 'Saved'}</span>
    </div>
  </div>;
}

function LogsPage({ portal }: { portal: string[] }) {
  const [source, setSource] = useState<string>('live');
  const [lines, setLines] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => request<{ lines: string[] }>(`/api/logs?source=${source}&lines=200`).then(data => { if (alive) setLines(data.lines); }).catch(() => undefined);
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [source]);
  return <div className="avsd-logs">
    <div className="avsd-row">
      {LOG_SOURCES.map(([id, label]) => <button key={id} className={source === id ? 'active' : ''} onClick={() => setSource(id)}>{label}</button>)}
    </div>
    <pre data-key-scroll>{lines.join('\n') || 'Nothing logged yet.'}</pre>
    <p className="avsd-note">Saved across reboots in ~/avsd/logs.{portal.length ? ` Download them from A/V over SD logs at ${portal[0]}` : ''}</p>
  </div>;
}

function UpdatePage({ status, job, locked, act, setConfirm }: { status: Status; job: Job | null; locked: boolean; act: Act; setConfirm: (confirm: Confirm) => void }) {
  const [files, setFiles] = useState<FirmwareFile[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  useEffect(() => {
    const load = () => request<{ files: FirmwareFile[] }>('/api/firmware').then(data => setFiles(data.files)).catch(() => undefined);
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, []);
  const toggle = (name: string) => setChosen(current => current.includes(name) ? current.filter(item => item !== name) : [...current, name]);
  const live = chosen.filter(name => files.some(file => file.name === name));
  const canSend = !locked && status.can.up && !status.can.listen_only;
  const noSelection = !canSend || !live.length;
  const run = (op: string) => void act('/api/rnse', { op, files: live });
  const { releases, teensy } = status;
  return <>
    {job && <section className={`avsd-job ${job.state}`}>
      <h2>{job.title}: {job.state === 'running' ? 'running' : job.state === 'ok' ? 'done' : 'failed'}</h2>
      {job.state === 'running' && job.name.startsWith('rnse-') && <p>The screen can go off while this runs and comes back by itself. A phone on the Pi's Wi-Fi can watch this page on port 5005.</p>}
      <pre data-key-scroll>{job.lines.join('\n')}</pre>
    </section>}

    <section>
      <h2>RNS-E firmware</h2>
      {!status.can.up || status.can.listen_only ? <p className="avsd-warning">Turn the ignition on to reach the RNS-E.</p> : null}
      {status.decoder.crc && <p className="avsd-note">Decoder last read as {status.decoder.crc}.</p>}
      {files.length === 0 && <p className="avsd-note">No files yet. {status.portal.length ? <>Connect to the Pi's Wi-Fi, go to {status.portal[0]} and upload to RNS-E firmware.</> : <>Copy sector images to {status.firmware_dir}.</>}</p>}
      <div className="avsd-files">
        {files.map(file => <button key={file.name} disabled={Boolean(file.problem) || locked} aria-pressed={live.includes(file.name)} className={live.includes(file.name) ? 'active' : ''} onClick={() => toggle(file.name)}>
          <strong>{file.name}</strong><small>{file.problem || `Sector ${file.sector} · CRC ${file.crc}`}</small>
        </button>)}
      </div>
      <div className="avsd-row">
        <button disabled={noSelection} onClick={() => run('check')}>Check</button>
        <button disabled={noSelection} onClick={() => run('rehearse')}>Dry run</button>
        <button className="danger" disabled={noSelection} onClick={() => setConfirm({
          title: `Flash ${flashTargets(live, files)}?`,
          body: 'The chain stops and the screen goes off for about a minute, then comes back by itself. Keep the ignition on. If the RNS-E does not come back, reinstall from the disc.',
          action: 'Flash',
          run: () => run('flash'),
        })}>Flash</button>
        <button disabled={!canSend} onClick={() => run('decoder')}>Read decoder</button>
      </div>
    </section>

    <section>
      <h2>Teensy</h2>
      <p className="avsd-note">In this version: {teensy.repo || 'none'}. Last flashed from here: {teensy.flashed || 'unknown'}.</p>
      <div className="avsd-row">
        <button disabled={locked || !teensy.present || !teensy.update_available} onClick={() => setConfirm({
          title: 'Flash the Teensy?',
          body: 'The chain stops while it flashes. If the picture does not return, power-cycle the RNS-E.',
          action: 'Flash',
          run: () => void act('/api/teensy/flash'),
        })}>Flash Teensy</button>
      </div>
    </section>

    <section>
      <h2>This app and the chain</h2>
      <p className="avsd-note">Version {releases.current?.version || 'unknown'}{releases.current?.branch ? ` on ${releases.current.branch}` : ''}.{releases.check?.message ? ` ${releases.check.message}` : ''} Updates with {releases.updates_with_rnse ? 'Update RNS-E' : 'Update A/V over SD'} in the Hudiy menu.</p>
      <div className="avsd-row">
        <button disabled={locked || !releases.previous} onClick={() => setConfirm({
          title: `Go back to ${releases.previous?.version}?`,
          body: 'The chain restarts on the previous version.',
          action: 'Go back',
          run: () => void act('/api/rollback'),
        })}>Previous version</button>
      </div>
    </section>
  </>;
}
