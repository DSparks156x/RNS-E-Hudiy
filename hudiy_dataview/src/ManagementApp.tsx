import { CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TouchTextInput } from './components/touchKeyboard/TouchTextInput';
import { HudiyColorScheme, useHudiyTheme } from './hooks/useHudiyTheme';
import { applyEdits, changedCount, ConfigSnapshot, ConfigTarget, displayValue, fieldsFor, filesPortalUrl, formatHexPayload, ManagedService, managementRequest, Metadata, parseSetting, SaveResult, SettingField } from './managementModel';
import './management.css';
import { VideoPanel } from './VideoPanel';
import { RnseBridgePanel } from './RnseBridgePanel';
import { RNSE_CONTROL_PATHS } from './rnseBridgeModel';
import { ManagerScrollRegion } from './ManagerScrollRegion';
import { installManagerPointerScroll } from './managerPointerScroll';

export type ManagementApi = <T>(path: string, init?: RequestInit) => Promise<T>;
interface Props { api?: ManagementApi; previewTheme?: HudiyColorScheme; }
type Message = { error: boolean; text: string };
const errorText = (error: unknown) => error instanceof Error ? error.message : 'The request failed.';
const writeHeaders = (pin: string) => ({ 'X-Hudiy-Management': '1', ...(pin ? { 'X-Hudiy-Pin': pin } : {}) });
const tidy = (path: string) => path.split('.').pop()?.replace(/_/g, ' ') || path;
function Icon({ kind }: { kind: 'settings' | 'services' | 'logs' | 'files' | 'refresh' }) {
  const paths = { settings: 'M19.4 13a7.6 7.6 0 0 0 0-2l2-1.5-2-3.5-2.3.9a8 8 0 0 0-1.7-1L15 3H9l-.4 2.9a8 8 0 0 0-1.7 1L4.6 6l-2 3.5 2 1.5a7.6 7.6 0 0 0 0 2l-2 1.5 2 3.5 2.3-.9a8 8 0 0 0 1.7 1L9 21h6l.4-2.9a8 8 0 0 0 1.7-1l2.3.9 2-3.5-2-1.5ZM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8Z', services: 'M4 3h16v6H4V3Zm0 12h16v6H4v-6Zm2-10v2h2V5H6Zm0 12v2h2v-2H6Zm5-6h2v2h-2v-2Z', logs: 'M4 3h16v18H4V3Zm3 4v2h10V7H7Zm0 4v2h10v-2H7Zm0 4v2h7v-2H7Z', files: 'M2 4h8l2 2h10v14H2V4Z', refresh: 'M17.7 6.3A8 8 0 1 0 20 12h-2a6 6 0 1 1-1.8-4.3L13 11h8V3l-3.3 3.3Z' };
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[kind]} /></svg>;
}

function SettingControl({ field, text, disabled, set }: { field: SettingField; text: string; disabled: boolean; set: (value: string) => void }) {
  const { metadata, value, path } = field;
  let error = '';
  try { parseSetting(text, value, metadata); } catch (reason) { error = errorText(reason); }
  const complex = metadata.type?.startsWith('json') || value === null || typeof value === 'object';
  const options = metadata.type === 'select' && typeof value === 'string' ? Array.from(new Set([value, ...(metadata.options || []).filter((option): option is string => typeof option === 'string')])) : null;
  return <div className={`manager-setting ${error ? 'has-error' : ''} ${metadata.type === 'hex-payload' ? 'manager-hex-setting' : ''}`}>
    <div className="manager-setting-label"><label htmlFor={`field-${path}`}>{metadata.label || tidy(path)}</label><p>{metadata.help || 'Setting from the installed configuration. The original JSON type and other settings are preserved.'}</p><code>{path}</code>{metadata.detailedHelp && <details><summary>More detail</summary><p>{metadata.detailedHelp}</p></details>}</div>
    <div className="manager-setting-value">{typeof value === 'boolean' && !complex ? <button id={`field-${path}`} type="button" className={`manager-switch ${text === 'true' ? 'on' : ''}`} role="switch" aria-checked={text === 'true'} aria-label={metadata.label || path} disabled={disabled} onClick={() => set(text === 'true' ? 'false' : 'true')}><span />{text === 'true' ? 'On' : 'Off'}</button>
      : options ? <select id={`field-${path}`} value={text} disabled={disabled} onChange={event => set(event.target.value)}>{options.map(option => <option key={option} value={option}>{option}</option>)}</select>
        : <TouchTextInput id={`field-${path}`} value={text} disabled={disabled} onValueChange={set} formatOnCommit={metadata.type === 'hex-payload' ? formatHexPayload : undefined} aria-label={metadata.label || path} touchOnly spellCheck={false} keyboardLayout={metadata.type === 'hex-payload' ? 'hex' : undefined} inputMode={typeof value === 'number' ? 'decimal' : 'text'} className={complex || metadata.type === 'hex-payload' ? 'manager-json-field' : ''} />}
      {complex && <small>JSON {Array.isArray(value) ? 'array' : value === null ? 'value' : 'object'}</small>}{error && <small className="manager-field-error" role="alert">{error}</small>}
    </div>
  </div>;
}

export function ManagementApp({ api = managementRequest, previewTheme }: Props = {}) {
  const { theme: nativeTheme } = useHudiyTheme(null);
  const [cachedTheme, setCachedTheme] = useState<HudiyColorScheme | null>(null);
  const [tab, setTab] = useState<'settings' | 'services' | 'logs'>('settings');
  const [metadata, setMetadata] = useState<Metadata>({});
  const [targets, setTargets] = useState<ConfigTarget[]>([]);
  const [targetId, setTargetId] = useState('rnse');
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [section, setSection] = useState('');
  const [rnsePane, setRnsePane] = useState<'head-unit' | 'automatic' | 'video'>('head-unit');
  const [search, setSearch] = useState('');
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [pending, setPending] = useState('');
  const [message, setMessage] = useState<Message | null>(null);
  const [pinRequired, setPinRequired] = useState(false);
  const [pin, setPin] = useState('');
  const [services, setServices] = useState<ManagedService[]>([]);
  const [serviceError, setServiceError] = useState('');
  const [logService, setLogService] = useState('dis_display');
  const [lineCount, setLineCount] = useState(100);
  const [logs, setLogs] = useState('');
  const [logError, setLogError] = useState('');
  const [follow, setFollow] = useState(true);
  const [logUpdated, setLogUpdated] = useState('');
  const [logBusy, setLogBusy] = useState(false);
  const configRequest = useRef(0);
  const logPane = useRef<HTMLPreElement>(null);
  const logSource = useRef('');
  const managerRoot = useRef<HTMLDivElement>(null);
  useEffect(() => managerRoot.current ? installManagerPointerScroll(managerRoot.current) : undefined, []);
  const theme = previewTheme || (window.hudiy ? nativeTheme : cachedTheme || nativeTheme);
  const themeVars = Object.fromEntries(Object.entries(theme).filter(([, value]) => typeof value === 'string').map(([key, value]) => [`--${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`, value]));
  const fields = useMemo(() => snapshot ? fieldsFor(snapshot.document, metadata, snapshot.id === 'rnse') : [], [snapshot, metadata]);
  const dirty = changedCount(fields, edits);
  const invalid = fields.some(field => { try { parseSetting(edits[field.id] ?? displayValue(field.value, field.metadata), field.value, field.metadata); return false; } catch { return true; } });
  const groups = useMemo<NonNullable<Metadata['sections']>>(() => {
    const present = new Set(fields.map(field => field.section));
    if (snapshot?.id === 'rnse') present.add('rnse');
    const definitions = snapshot?.id === 'rnse' ? [{ ...(metadata.sections || []).find(group => group.id === 'rnse'), id: 'rnse', title: 'RNS-E', root: 'rnse' }, ...(metadata.sections || []).filter(group => group.id !== 'rnse')] : metadata.sections || [];
    const known = definitions.filter(group => present.has(group.id));
    const extra = [...present].filter(id => !known.some(group => group.id === id)).map(id => ({ id, title: id === 'additional' ? 'Additional settings' : tidy(id) }));
    return [...known, ...extra];
  }, [fields, metadata, snapshot?.id]);
  const activeGroup = groups.find(group => group.id === section) || groups[0];
  const rnseSelected = snapshot?.id === 'rnse' && activeGroup?.id === 'rnse' && !search.trim();
  const videoSelected = rnseSelected && rnsePane === 'video';
  const liveSelected = rnseSelected && rnsePane === 'head-unit';
  const visibleFields = fields.filter(field => search.trim() ? `${field.path} ${field.metadata.label || ''} ${field.metadata.help || ''} ${displayValue(field.value, field.metadata)}`.toLowerCase().includes(search.trim().toLowerCase()) : field.section === activeGroup?.id);
  const brightnessFields = rnseSelected ? visibleFields.filter(field => RNSE_CONTROL_PATHS.has(field.path)) : [];

  const loadConfig = useCallback(async (id: string) => {
    const request = ++configRequest.current; setLoadingConfig(true); setSnapshot(null); setEdits({});
    try { const result = await api<ConfigSnapshot>(`/configs/${encodeURIComponent(id)}`); if (request === configRequest.current) { setSnapshot(result); setEdits({}); setSection(''); } }
    catch (error) { if (request === configRequest.current) { setSnapshot(null); setMessage({ error: true, text: errorText(error) }); } }
    finally { if (request === configRequest.current) setLoadingConfig(false); }
  }, [api]);
  useEffect(() => { void loadConfig(targetId); return () => { configRequest.current++; }; }, [targetId, loadConfig]);
  useEffect(() => {
    let alive = true;
    void api<{ configs: ConfigTarget[]; pin_required?: boolean }>('/configs').then(result => { if (alive) { setTargets(result.configs); setPinRequired(!!result.pin_required); } }).catch(error => { if (alive) setMessage({ error: true, text: errorText(error) }); });
    void api<Metadata>('/metadata').then(result => { if (alive) setMetadata(result); }).catch(() => { /* Unknown settings remain editable without description metadata. */ });
    const update = () => api<{ theme?: HudiyColorScheme }>('/theme').then(result => { if (alive && result.theme) setCachedTheme(result.theme); }).catch(() => undefined);
    void update(); const interval = window.setInterval(() => void update(), 30000);
    return () => { alive = false; window.clearInterval(interval); };
  }, [api]);
  const refreshServices = useCallback(async () => {
    try { const result = await api<{ services: ManagedService[] }>('/services'); setServices(result.services); setServiceError(''); setLogService(previous => result.services.some(service => service.id === previous) ? previous : result.services[0]?.id || ''); }
    catch (error) { setServiceError(errorText(error)); }
  }, [api]);
  useEffect(() => { void refreshServices(); }, [refreshServices]);
  useEffect(() => {
    if (tab !== 'services') return undefined;
    const interval = window.setInterval(() => { if (!pending) void refreshServices(); }, 5000);
    return () => window.clearInterval(interval);
  }, [tab, pending, refreshServices]);
  useEffect(() => {
    if (tab !== 'logs' || !logService) return undefined;
    let alive = true, busy = false;
    const source = `${logService}:${lineCount}`;
    const sourceChanged = logSource.current !== source;
    logSource.current = source;
    if (sourceChanged) { setLogs(''); setLogUpdated(''); }
    const update = async () => {
      if (busy) return; busy = true; if (alive) setLogBusy(true);
      try { const result = await api<{ text: string }>(`/services/${encodeURIComponent(logService)}/logs?lines=${lineCount}`); if (alive) { setLogs(result.text); setLogError(''); setLogUpdated(new Date().toLocaleTimeString()); } }
      catch (error) { if (alive) setLogError(errorText(error)); }
      finally { busy = false; if (alive) setLogBusy(false); }
    };
    if (sourceChanged || follow) void update();
    const interval = follow ? window.setInterval(() => void update(), 3000) : null;
    return () => { alive = false; setLogBusy(false); if (interval !== null) window.clearInterval(interval); };
  }, [tab, logService, lineCount, follow, api]);
  useEffect(() => { if (follow && logPane.current) logPane.current.scrollTop = logPane.current.scrollHeight; }, [logs, follow]);

  const save = async () => {
    if (!snapshot || !dirty || invalid || pending) return;
    setPending('save'); setMessage(null);
    try {
      const document = applyEdits(snapshot.document, fields, edits);
      const result = await api<SaveResult>(`/configs/${encodeURIComponent(snapshot.id)}`, { method: 'PUT', headers: { ...writeHeaders(pin), 'Content-Type': 'application/json' }, body: JSON.stringify({ document, revision: snapshot.revision }) });
      setSnapshot({ ...snapshot, ...result, document: result.document || document }); setEdits({});
      let liveMessage = '';
      if (snapshot.id === 'rnse' && fields.some(field => field.path.startsWith('rnse.') && field.id in edits && edits[field.id] !== displayValue(field.value, field.metadata))) {
        try { await api('/rnse-control/reload', { method: 'POST', headers: { ...writeHeaders(pin), 'Content-Type': 'application/json' }, body: '{}' }); liveMessage = ' RNS-E live settings updated.'; }
        catch (error) { liveMessage = ` RNS-E live settings could not update: ${errorText(error)} Restart RNS-E functions in Services.`; }
      }
      setMessage({ error: false, text: `Saved.${result.backup ? ` Backup: ${result.backup}.` : ''}${liveMessage} ${result.affected_services?.length ? `Restart other affected services when ready: ${result.affected_services.join(', ')}.` : 'Services were not restarted.'}` });
    } catch (error) { setMessage({ error: true, text: `${errorText(error)} Your draft is still here.` }); }
    finally { setPending(''); }
  };
  const serviceAction = async (service: ManagedService, action: string) => {
    if (pending) return; setPending(`${service.id}:${action}`); setMessage(null);
    try { const result = await api<{ message?: string }>(`/services/${encodeURIComponent(service.id)}/${action}`, { method: 'POST', headers: writeHeaders(pin) }); setMessage({ error: false, text: result.message || `${action} requested for ${service.label}.` }); await refreshServices(); }
    catch (error) { setMessage({ error: true, text: errorText(error) }); }
    finally { setPending(''); }
  };
  const refreshLogs = async () => {
    if (logBusy || !logService) return; setLogBusy(true);
    const source = `${logService}:${lineCount}`;
    try { const result = await api<{ text: string }>(`/services/${encodeURIComponent(logService)}/logs?lines=${lineCount}`); if (logSource.current === source) { setLogs(result.text); setLogError(''); setLogUpdated(new Date().toLocaleTimeString()); } }
    catch (error) { if (logSource.current === source) setLogError(errorText(error)); } finally { setLogBusy(false); }
  };

  return <div ref={managerRoot} className="container manager-container" data-theme={theme.darkThemeEnabled ? 'dark' : 'light'} style={themeVars as CSSProperties}>
    <nav className="manager-tabs" aria-label="Manager panels"><strong className="manager-nav-title">RNS-E Manager</strong>{(['settings', 'services', 'logs'] as const).map(id => <button key={id} className={tab === id ? 'active' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}><Icon kind={id} />{id[0].toUpperCase() + id.slice(1)}</button>)}<a href={filesPortalUrl(window.location)}><Icon kind="files" />Files</a>{pinRequired && <TouchTextInput className="manager-pin" type="password" value={pin} onValueChange={setPin} aria-label="Management PIN" placeholder="PIN" touchOnly />}</nav>
    {message && <div className={`manager-message ${message.error ? 'error' : ''}`} role={message.error ? 'alert' : 'status'}><span>{message.text}</span><button aria-label="Dismiss message" onClick={() => setMessage(null)}>×</button></div>}
    {tab === 'settings' && <>
      {!videoSelected && <div className="manager-settings-tools"><select aria-label="Configuration file" value={targetId} disabled={!!pending || !!dirty} onChange={event => { setTargetId(event.target.value); setSearch(''); setMessage(null); }}>{targets.length ? targets.map(target => <option key={target.id} value={target.id}>{target.label}{target.exists ? '' : ' (missing)'}</option>) : <option value="rnse">RNSE configuration</option>}</select><TouchTextInput value={search} onValueChange={setSearch} aria-label="Search settings" placeholder="Search settings" touchOnly /><button className="manager-icon-button" disabled={!!pending || !!dirty || loadingConfig} onClick={() => void loadConfig(targetId)} aria-label="Reload configuration"><Icon kind="refresh" /></button></div>}
      <div className="manager-settings-workspace"><aside className="manager-sections" aria-label="Settings sections">{groups.map(group => <button className={activeGroup?.id === group.id && !search ? 'active' : ''} key={group.id} onClick={() => { setSection(group.id); setSearch(''); }}>{group.title}</button>)}</aside>
        <ManagerScrollRegion>{loadingConfig ? <p className="manager-empty">Loading installed configuration…</p> : snapshot ? <>
          {!videoSelected && !rnseSelected && <div className="manager-section-heading"><h2>{search ? `Search · ${visibleFields.length} settings` : activeGroup?.title}</h2><p>{search ? 'Names, values and descriptions.' : activeGroup?.description}</p></div>}
          {rnseSelected && <nav className="manager-rnse-panels" aria-label="RNS-E controls"><button className={rnsePane === 'head-unit' ? 'active' : ''} aria-pressed={rnsePane === 'head-unit'} onClick={() => setRnsePane('head-unit')}>Live controls</button><button className={rnsePane === 'automatic' ? 'active' : ''} aria-pressed={rnsePane === 'automatic'} onClick={() => setRnsePane('automatic')}>Automatic{dirty ? ' · unsaved edits' : ''}</button><button className={rnsePane === 'video' ? 'active' : ''} aria-pressed={rnsePane === 'video'} onClick={() => setRnsePane('video')}>Pi video</button></nav>}
          {videoSelected ? <VideoPanel api={api} pin={pin} /> : <>{rnseSelected && <RnseBridgePanel view={liveSelected ? 'live' : 'automatic'} fields={brightnessFields} edits={edits} disabled={!!pending || (pinRequired && !pin)} api={api} pin={pin} set={(id, text) => setEdits(previous => ({ ...previous, [id]: text }))} />}{!liveSelected && visibleFields.filter(field => !brightnessFields.includes(field)).map(field => <SettingControl field={field} key={field.id} text={edits[field.id] ?? displayValue(field.value, field.metadata)} disabled={!!pending} set={text => setEdits(previous => ({ ...previous, [field.id]: text }))} />)}{!visibleFields.length && <p className="manager-empty">{rnseSelected ? 'No head-unit settings in this config. Pi video is available above.' : 'No settings match.'}</p>}</>}
        </> : <div className="manager-empty">Could not load this configuration.<button onClick={() => void loadConfig(targetId)}>Try again</button></div>}</ManagerScrollRegion>
      </div>
      {!videoSelected && !liveSelected && <footer className="manager-savebar"><div><strong>{dirty ? `${dirty} unsaved ${dirty === 1 ? 'change' : 'changes'}` : 'Installed configuration'}</strong><small>{snapshot?.filename || 'No file loaded'}{invalid ? ' · Fix invalid fields before applying.' : ''}</small></div><button disabled={!!pending || !dirty} onClick={() => { setEdits({}); setMessage(null); }}>Discard</button><button className="manager-primary" disabled={!!pending || !dirty || invalid || !snapshot || (pinRequired && !pin)} onClick={() => void save()}>{pending === 'save' ? 'Saving…' : 'Apply'}</button></footer>}
    </>}
    {tab === 'services' && <main className="manager-panel-scroll"><div className="manager-panel-heading"><div><h2>Services</h2><p>Restart after changing settings. Stopping a service pauses its display, controls or recordings.</p></div><button className="manager-icon-button" aria-label="Refresh services" disabled={!!pending} onClick={() => void refreshServices()}><Icon kind="refresh" /></button></div>{serviceError && <p className="manager-inline-error" role="alert">{serviceError}</p>}{!services.length && !serviceError && <p className="manager-empty">Loading service status…</p>}<div className="manager-service-list">{services.map(service => <article className="manager-service" key={service.id}><div><div className="manager-service-title"><h3>{service.label}</h3><span className={`manager-status ${service.active_state === 'active' ? 'running' : ''}`}>{service.active_state} · {service.sub_state}</span></div><p>{service.description || service.unit}</p>{service.error && <p className="manager-inline-error">{service.error}</p>}{service.id === 'hudiy_dataview' && <small>Stops DataView, its file portal and active DataView recordings.</small>}</div><div className="manager-service-actions">{(['start', 'stop', 'restart'] as const).map(action => <button disabled={!service.can_control || !!pending || (pinRequired && !pin)} key={action} onClick={() => void serviceAction(service, action)}>{pending === `${service.id}:${action}` ? 'Working…' : action[0].toUpperCase() + action.slice(1)}</button>)}<button onClick={() => { setLogService(service.id); setTab('logs'); }}>Logs</button></div></article>)}</div></main>}
    {tab === 'logs' && <main className="manager-logs-panel"><div className="manager-log-tools"><select aria-label="Log service" value={logService} onChange={event => setLogService(event.target.value)}>{services.map(service => <option value={service.id} key={service.id}>{service.label}</option>)}</select><select aria-label="Number of recent log lines" value={lineCount} onChange={event => setLineCount(Number(event.target.value))}>{[50, 100, 250, 500].map(count => <option value={count} key={count}>{count} lines</option>)}</select><button className={follow ? 'manager-primary' : ''} aria-pressed={follow} onClick={() => setFollow(previous => !previous)}>{follow ? 'Following' : 'Paused'}</button><button className="manager-icon-button" disabled={logBusy} aria-label="Refresh logs" onClick={() => void refreshLogs()}><Icon kind="refresh" /></button></div>{logError && <p className="manager-inline-error" role="alert">{logError} Last received lines remain below.</p>}<pre ref={logPane} className="manager-log-text" aria-label="Recent service log">{logs || (logBusy ? 'Loading recent log…' : 'No recent lines returned.')}</pre><div className="manager-log-footer">{logUpdated ? `Last received ${logUpdated}` : 'Waiting for a log response'} · {follow ? 'Refreshes every 3 seconds' : 'Automatic refresh paused'}</div></main>}
  </div>;
}


