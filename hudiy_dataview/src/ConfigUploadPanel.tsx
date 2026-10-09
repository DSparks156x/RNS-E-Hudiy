import { useEffect, useRef, useState } from 'react';
import { TouchTextInput } from './components/touchKeyboard/TouchTextInput';
import { ConfigSnapshot, ConfigTarget, managementRequest, parseSetting, SaveResult } from './managementModel';
import './configUpload.css';

export function ConfigUploadPanel() {
  const [targets, setTargets] = useState<ConfigTarget[]>([]);
  const [target, setTarget] = useState('rnse');
  const [snapshot, setSnapshot] = useState<ConfigSnapshot | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pinRequired, setPinRequired] = useState(false);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const input = useRef<HTMLInputElement>(null);
  const sequence = useRef(0);
  const fileSequence = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    let active = true;
    managementRequest<{ configs: ConfigTarget[]; pin_required: boolean }>('/configs').then(data => {
      if (active) { setTargets(data.configs); setPinRequired(data.pin_required); }
    }).catch(reason => { if (active) { setError(reason instanceof Error ? reason.message : 'Configuration access is unavailable.'); setLoading(false); } });
    return () => { active = false; mounted.current = false; sequence.current++; fileSequence.current++; };
  }, []);
  const load = async (id: string) => {
    const request = ++sequence.current;
    setSnapshot(null); setLoading(true); setError('');
    try {
      const data = await managementRequest<ConfigSnapshot>(`/configs/${encodeURIComponent(id)}`);
      if (request === sequence.current) setSnapshot(data);
    } catch (reason) { if (request === sequence.current) setError(reason instanceof Error ? reason.message : 'Could not read configuration.'); }
    finally { if (mounted.current && request === sequence.current) setLoading(false); }
  };
  useEffect(() => { if (targets.length) void load(target); }, [target, targets.length]);
  const choose = async (candidate: File | null) => {
    const request = ++fileSequence.current;
    setFile(null); setError(''); setMessage('');
    if (!candidate) return;
    if (candidate.size > 2 * 1024 * 1024) { setError('Choose a JSON file smaller than 2 MiB.'); return; }
    try {
      parseSetting((await candidate.text()).replace(/^\uFEFF/, ''), {}, { type: 'json' });
      if (mounted.current && request === fileSequence.current) setFile(candidate);
    } catch (reason) { if (mounted.current && request === fileSequence.current) setError(reason instanceof Error ? reason.message : 'Invalid JSON file.'); }
  };
  const replace = async () => {
    if (!snapshot || !file || busy) return;
    const id = target;
    const request = sequence.current;
    setBusy(true); setError(''); setMessage('');
    const form = new FormData(); form.append('file', file); form.append('revision', snapshot.revision);
    try {
      const result = await managementRequest<SaveResult>(`/configs/${encodeURIComponent(id)}/import`, {
        method: 'POST', headers: { 'X-Hudiy-Management': '1', ...(pin ? { 'X-Hudiy-Pin': pin } : {}) }, body: form,
      });
      if (!mounted.current || request !== sequence.current) return;
      setSnapshot({ ...snapshot, ...result }); setFile(null); if (input.current) input.current.value = '';
      setMessage(`${result.message || 'Configuration replaced.'}${result.backup ? ` Backup: ${result.backup}.` : ''} ${id === 'rnse' ? 'Restart the affected services in RNS-E Manager to apply changes.' : 'Restart Hudiy to apply changes.'}`);
    } catch (reason) { if (mounted.current && request === sequence.current) setError(`${reason instanceof Error ? reason.message : 'Replacement failed.'} Your selected file has been kept. Refresh the current revision before retrying if it changed.`); }
    finally { if (mounted.current && request === sequence.current) setBusy(false); }
  };
  return <article className="portal-card config-upload-card">
    <div className="collection-summary"><div><h2>Replace a configuration</h2><p>Upload config.json or one of Hudiy’s config files. The current file is backed up before replacement; services keep running until you restart them.</p></div></div>
    <label className="portal-field-label" htmlFor="config-upload-target">Replace on the Pi</label>
    <select className="portal-select" id="config-upload-target" disabled={busy || !targets.length} value={target} onChange={event => { sequence.current++; fileSequence.current++; setSnapshot(null); setTarget(event.target.value); setFile(null); setMessage(''); if (input.current) input.current.value = ''; }}>{targets.map(item => <option key={item.id} value={item.id}>{item.label} · {item.filename}</option>)}</select>
    <p className="portal-safety-note">{snapshot ? `Current file: ${snapshot.filename}. The upload replaces its entire contents.` : loading ? 'Reading the current configuration…' : 'Current configuration unavailable. Refresh before replacing.'}</p>
    <input ref={input} type="file" accept=".json,application/json" disabled={busy || !snapshot} onChange={event => void choose(event.target.files?.[0] || null)} aria-label="Choose configuration JSON" />
    {file && <p>{file.name} · {(file.size / 1024).toFixed(1)} KiB · JSON parsed</p>}
    {pinRequired && <label className="portal-pin-label">Upload PIN<TouchTextInput className="portal-pin" aria-label="Configuration upload PIN" touchOnly type="password" autoComplete="off" value={pin} disabled={busy} onValueChange={setPin} /></label>}
    <div className="config-upload-actions"><button className="portal-primary-button" disabled={!file || !snapshot || busy || (pinRequired && !pin)} onClick={() => void replace()}>{busy ? 'Replacing…' : 'Validate & replace config'}</button><button className="portal-text-button" disabled={busy || !targets.length} onClick={() => void load(target)}>Refresh current revision</button></div>
    {error && <p className="portal-validation" role="alert">{error}</p>}{message && <p className="portal-safety-note" role="status">{message}</p>}
  </article>;
}
