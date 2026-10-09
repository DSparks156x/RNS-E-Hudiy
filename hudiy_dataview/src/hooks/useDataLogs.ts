import { useCallback, useEffect, useRef, useState } from 'react';
import { Socket } from 'socket.io-client';
import { LogConfig, LogReview, LogState, Recording } from '../components/dataLogs/model';

export async function logRequest<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/data-logs${path}`, { method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const data = await response.json();
  if (!response.ok || data.error || data.status === 'error') throw new Error(typeof data.error === 'string' ? data.error : data.message || `Request failed (${response.status})`);
  return data as T;
}

export function useDataLogs(socket: Socket | null, active: boolean) {
  const [state, setState] = useState<LogState | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const loaded = useRef(false);
  const reviewSequence = useRef(0);
  const refresh = useCallback(async () => {
    try { const data = await logRequest<LogState>(); setState(data); setError(''); loaded.current = true; }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { if (active && !loaded.current) void refresh(); }, [active, refresh]);
  useEffect(() => {
    if (!socket) return;
    const receive = (data: LogState) => { setState(data); loaded.current = true; };
    const receiveStatus = (recording: Recording) => setState(previous => previous ? { ...previous, recording } : previous);
    const reconnect = () => { if (loaded.current || active) void refresh(); };
    socket.on('data_logs_state', receive);
    socket.on('data_logs_status', receiveStatus);
    socket.on('connect', reconnect);
    return () => { socket.off('data_logs_state', receive); socket.off('data_logs_status', receiveStatus); socket.off('connect', reconnect); };
  }, [socket, active, refresh]);
  useEffect(() => {
    if (!active || !state?.recording.recording) return;
    const timer = window.setInterval(() => {
      void logRequest<Recording>('/status').then(recording => setState(previous => previous ? { ...previous, recording } : previous))
        .catch(e => setError(e instanceof Error ? e.message : String(e)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [active, state?.recording.recording, refresh]);
  const mutate = useCallback(async (path: string, body: unknown, method = 'POST') => {
    setPending(true); setError('');
    try { const result = await logRequest<Record<string, unknown>>(path, method, body); await refresh(); return result; }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); return null; }
    finally { setPending(false); }
  }, [refresh]);
  const save = useCallback((config: LogConfig) => mutate('/config', config, 'PUT'), [mutate]);
  const review = useCallback(async (id: string, range: { window_sec?: number; since?: number; until?: number } = { window_sec: 30 }): Promise<LogReview | null> => {
    const sequence = ++reviewSequence.current;
    setPending(true); setError('');
    try { const query = new URLSearchParams(Object.entries(range).map(([key, value]) => [key, String(value)])); const result = await logRequest<LogReview>(`/sessions/${encodeURIComponent(id)}?${query}`); return sequence === reviewSequence.current ? result : null; }
    catch (e) { if (sequence === reviewSequence.current) setError(e instanceof Error ? e.message : String(e)); return null; }
    finally { if (sequence === reviewSequence.current) setPending(false); }
  }, []);
  return { state, error, pending, refresh, mutate, save, review };
}
