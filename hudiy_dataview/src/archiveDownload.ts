export interface ArchiveJobStatus {
  state: 'queued' | 'preparing' | 'ready' | 'error';
  percent: number;
  bytes_processed: number;
  total_bytes: number;
  current_file: string | null;
  error: string | null;
  status_url: string;
  download_url: string | null;
}

export interface ArchiveJobStart { status_url: string; }

export interface ArchivePreparationOptions {
  archiveUrl: string;
  fetcher?: typeof fetch;
  wait?: (milliseconds: number, signal?: AbortSignal) => Promise<void>;
  onStatus?: (status: ArchiveJobStatus) => void;
  signal?: AbortSignal;
  pollIntervalMs?: number;
  timeoutMs?: number;
}

const defaultWait = (milliseconds: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  if (signal?.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
  const onAbort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
  const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, milliseconds);
  signal?.addEventListener('abort', onAbort, { once: true });
});

async function responseJson<T>(response: Response, action: string): Promise<T> {
  let body: unknown;
  try { body = await response.json(); } catch { body = null; }
  if (!response.ok) {
    const message = body && typeof body === 'object' && 'error' in body ? String(body.error) : `${action} (${response.status}).`;
    throw new Error(message);
  }
  if (!body || typeof body !== 'object') throw new Error(`${action}: invalid server response.`);
  return body as T;
}

export async function prepareArchive({ archiveUrl, fetcher = fetch, wait = defaultWait, onStatus,
  signal, pollIntervalMs = 750, timeoutMs = 10 * 60_000 }: ArchivePreparationOptions): Promise<ArchiveJobStatus> {
  const startedAt = Date.now();
  const controller = new AbortController();
  let timedOut = false;
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort, { once: true });
  const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    if (signal?.aborted) controller.abort();
    const startResponse = await fetcher(archiveUrl, { method: 'POST', signal: controller.signal });
    const job = await responseJson<ArchiveJobStart>(startResponse, 'Could not start ZIP preparation');
    if (!job.status_url) throw new Error('Could not start ZIP preparation: missing status URL.');

    while (Date.now() - startedAt < timeoutMs) {
      if (controller.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      const statusResponse = await fetcher(job.status_url, { signal: controller.signal });
      const status = await responseJson<ArchiveJobStatus>(statusResponse, 'Could not check ZIP preparation');
      onStatus?.(status);
      if (status.state === 'ready') {
        if (!status.download_url) throw new Error('ZIP is ready, but the download link is missing.');
        return status;
      }
      if (status.state === 'error') throw new Error(status.error || 'ZIP preparation failed.');
      if (status.state !== 'queued' && status.state !== 'preparing') throw new Error('ZIP preparation returned an unknown status.');
      await wait(pollIntervalMs, controller.signal);
    }
    throw new Error('ZIP preparation timed out. Try again.');
  } catch (error) {
    if (timedOut) throw new Error('ZIP preparation timed out. Try again.');
    throw error;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', onAbort);
  }
}
