import { useEffect, useState } from 'react';
import { Socket } from 'socket.io-client';

interface Props { socket: Socket | null; theme: Record<string, string>; onBack: () => void }
interface Artifact { artifact_id: string; name: string; size_bytes: number }

export function ExhaustValvePanel({ socket, theme, onBack }: Props) {
    const [target, setTarget] = useState<number | null>(null);
    const [inhibited, setInhibited] = useState(true);
    const [files, setFiles] = useState<Artifact[]>([]);
    const [selected, setSelected] = useState('');
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState('');
    const [percent, setPercent] = useState(0);
    const [armed, setArmed] = useState(false);
    const [commandPending, setCommandPending] = useState(false);
    useEffect(() => {
        if (!socket) return;
        const refresh = () => socket.emit('get_exhaust_valve');
        let lastResult = '';
        const status = (data: any) => {
            setTarget(data.target ?? null); setInhibited(Boolean(data.inhibited)); setCommandPending(false);
            if (typeof data.update_running === 'boolean') setBusy(data.update_running);
            if ('update_result' in data) {
                const result = JSON.stringify(data.update_result || null);
                if (result !== lastResult && data.update_result?.message) setMessage(data.update_result.message);
                lastResult = result;
            }
        };
        const artifacts = (items: Artifact[]) => {
            setFiles(items); setSelected(prev => items.some(item => item.artifact_id === prev)
                ? prev : items[0]?.artifact_id || '');
        };
        const started = () => { setBusy(true); setArmed(false); setMessage('Preparing update…'); setPercent(0); };
        const progress = (data: any) => { setBusy(true); setPercent(data.percent); setMessage(data.detail); };
        const complete = (data: any) => { setBusy(false); setMessage(data.message); refresh(); };
        const error = (data: any) => {
            if (data.stopped !== false) setBusy(false);
            setCommandPending(false); setArmed(false); setMessage(data.message);
        };
        const disconnected = () => {
            setInhibited(true); setCommandPending(false); setArmed(false);
            setMessage('Connection lost; command and update status unconfirmed.');
        };
        socket.on('connect', refresh); socket.on('disconnect', disconnected);
        socket.on('exhaust_valve_status', status); socket.on('exhaust_valve_artifacts', artifacts);
        socket.on('exhaust_valve_started', started); socket.on('exhaust_valve_progress', progress);
        socket.on('exhaust_valve_complete', complete); socket.on('exhaust_valve_error', error);
        refresh();
        const timer = setInterval(refresh, 3000);
        return () => {
            clearInterval(timer);
            socket.off('connect', refresh); socket.off('disconnect', disconnected);
            socket.off('exhaust_valve_status', status); socket.off('exhaust_valve_artifacts', artifacts);
            socket.off('exhaust_valve_started', started); socket.off('exhaust_valve_progress', progress);
            socket.off('exhaust_valve_complete', complete); socket.off('exhaust_valve_error', error);
        };
    }, [socket]);
    const button = { padding: '12px 18px', borderRadius: '8px', border: 'none',
        background: theme.primaryContainer, color: theme.onPrimaryContainer, fontSize: '1rem' };
    const update = (dry_run: boolean) => {
        setBusy(true); setArmed(false);
        socket?.emit('start_exhaust_valve_update', { artifact_id: selected, dry_run });
    };
    return <section style={{ padding: '15px', color: theme.onSurface, overflow: 'auto', height: '100%', boxSizing: 'border-box' }}>
        <button style={button} onClick={onBack}>Back</button>
        <h2>Exhaust valve controller</h2>
        <p>Last requested target: {target === null ? 'Unknown' : target === 100 ? 'Open' : target === 0 ? 'Closed' : `${target}%`}. Unconfirmed.</p>
        <div style={{ display: 'flex', gap: '12px' }}>
            {[{ label: 'Open', target: 100 }, { label: 'Close', target: 0 }].map(item =>
                <button key={item.target} style={button} disabled={!socket?.connected || busy || inhibited || commandPending}
                    onClick={() => { setCommandPending(true); setMessage(`${item.label} requested (unconfirmed)`); socket?.emit('exhaust_valve_command', { target: item.target }); }}>
                    {item.label}
                </button>)}
        </div>
        <p>The controller remembers its target and restores it at power-up. No vehicle feedback is available.</p>
        <h3>Firmware update</h3>
        <p>Upload a ZIP containing can-update.json and both slot .bin images to Exhaust valve controller in <a href="/files" style={{ color: theme.primary }}>Files</a>, then refresh. The three files can also be uploaded separately.</p>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
            <select aria-label="Valve firmware bundle" value={selected} disabled={busy} onChange={event => { setSelected(event.target.value); setArmed(false); }}
                style={{ ...button, maxWidth: '100%' }}>
                {files.length === 0 && <option value="">No complete validated bundles</option>}
                {files.map(file => <option key={file.artifact_id} value={file.artifact_id}>{file.name} ({Math.round(file.size_bytes / 1024)} KiB)</option>)}
            </select>
            <button style={button} disabled={busy} onClick={() => socket?.emit('get_exhaust_valve')}>Refresh</button>
            <button style={button} disabled={busy || !selected || !socket?.connected} onClick={() => update(true)}>Validate only</button>
            <button style={button} disabled={busy || !selected || !socket?.connected}
                onClick={() => armed ? update(false) : setArmed(true)}>{armed ? 'Confirm firmware update' : 'Update firmware'}</button>
            {armed && <button style={button} onClick={() => setArmed(false)}>Dismiss</button>}
            {busy && <button style={button} onClick={() => socket?.emit('cancel_exhaust_valve_update')}>Stop transfer</button>}
        </div>
        {armed && <p>Send both slots with three passes. Valve controls pause during transfer; the controller preserves its remembered target. Completion reports sent / unconfirmed.</p>}
        {busy && <progress style={{ width: '100%', marginTop: '15px' }} max={100} value={percent} />}
        <p role="status">{message}</p>
    </section>;
}
