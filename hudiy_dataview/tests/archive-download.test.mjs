import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/archiveDownload.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { prepareArchive } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const status = (state, extra = {}) => ({ state, percent: state === 'preparing' ? 35 : state === 'ready' ? 100 : 0,
  bytes_processed: state === 'preparing' ? 350 : 0, total_bytes: 1000, current_file: null, error: null,
  status_url: '/status/job-1', download_url: state === 'ready' ? '/download/job-1' : null, ...extra });

test('starts one archive job, polls sequentially, reports progress, and returns ready download URL', async () => {
  const calls = []; const reported = []; let activePolls = 0; let peakPolls = 0;
  const fetcher = async (url, options = {}) => {
    calls.push([url, options.method || 'GET']);
    if (options.method === 'POST') return json({ status_url: '/status/job-1' }, 202);
    activePolls++; peakPolls = Math.max(peakPolls, activePolls);
    await Promise.resolve(); activePolls--;
    return json(reported.length ? status('ready') : status('preparing'));
  };
  const result = await prepareArchive({ archiveUrl: '/api/archive', fetcher, wait: async () => {}, onStatus: value => reported.push(value) });
  assert.deepEqual(calls, [['/api/archive', 'POST'], ['/status/job-1', 'GET'], ['/status/job-1', 'GET']]);
  assert.equal(peakPolls, 1);
  assert.equal(reported[0].bytes_processed, 350);
  assert.equal(result.download_url, '/download/job-1');
});

test('reports rejected archive start and HTTP failures', async () => {
  await assert.rejects(prepareArchive({ archiveUrl: '/archive', fetcher: async () => json({ error: 'Busy' }, 409) }), /Busy/);
  let call = 0;
  await assert.rejects(prepareArchive({ archiveUrl: '/archive', fetcher: async () => ++call === 1
    ? json({ status_url: '/status' }, 202) : json({ error: 'Status unavailable' }, 503) }), /Status unavailable/);
});

test('reports server job errors and missing download links', async () => {
  await assert.rejects(prepareArchive({ archiveUrl: '/archive', fetcher: async url => url === '/archive'
    ? json({ status_url: '/status' }, 202) : json(status('error', { error: 'Disk full' })) }), /Disk full/);
  await assert.rejects(prepareArchive({ archiveUrl: '/archive', fetcher: async url => url === '/archive'
    ? json({ status_url: '/status' }, 202) : json(status('ready', { download_url: null })) }), /download link is missing/);
});

test('aborts an in-flight request at the preparation deadline', async () => {
  await assert.rejects(prepareArchive({ archiveUrl: '/archive', timeoutMs: 10, fetcher: (_url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  }) }), /timed out/);
});
