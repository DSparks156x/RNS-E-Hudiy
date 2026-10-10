import { TouchTextInput } from '../components/touchKeyboard/TouchTextInput';
import { ConfigUploadPanel } from '../ConfigUploadPanel';
import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from 'react';
import { collectionGroup, FileGroup, folderFiles, PortalCatalog, PortalFile, validateFile, visibleFiles } from '../filePortalModel';
import { ArchiveJobStatus, prepareArchive } from '../archiveDownload';

export interface FilesTabProps {
  loadCatalog?: () => Promise<PortalCatalog>;
  sendFile?: (target: string, file: File, pin: string, progress: (percent: number) => void) => Promise<string>;
  initialGroup?: FileGroup;
  initialCollection?: string;
}
const loadCatalog = async (): Promise<PortalCatalog> => {
  const response = await fetch('/api/files');
  if (!response.ok) throw new Error(`Could not load files (${response.status}).`);
  return response.json();
};
const sendFile: NonNullable<FilesTabProps['sendFile']> = (target, file, pin, progress) => new Promise((resolve, reject) => {
  const form = new FormData(); form.append('file', file);
  const xhr = new XMLHttpRequest(); xhr.open('POST', `/api/files/upload/${encodeURIComponent(target)}`);
  if (pin) xhr.setRequestHeader('X-Hudiy-Pin', pin);
  xhr.upload.onprogress = event => { if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100)); };
  xhr.onload = () => {
    let body: { message?: string; error?: string } = {};
    try { body = JSON.parse(xhr.responseText); } catch { /* Fall back to the HTTP status. */ }
    if (xhr.status >= 200 && xhr.status < 300) resolve(body.message || 'File validated and saved.');
    else reject(new Error(body.error || `Upload failed (${xhr.status}).`));
  };
  xhr.onerror = () => reject(new Error('Connection lost during upload.'));
  xhr.onabort = () => reject(new Error('Upload interrupted.'));
  xhr.send(form);
});
export const formatSize = (bytes: number) => bytes < 1024 ? `${bytes} B`
  : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`
  : `${(bytes / 1024 ** 2).toFixed(bytes < 10 * 1024 ** 2 ? 1 : 0)} MB`;
const formatDate = (timestamp: number) => new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
}).format(new Date(timestamp * 1000));
function Icon({ name }: { name: 'download' | 'upload' | 'folder' | 'refresh' | 'search' | 'close' }) {
  const paths = {
    download: 'M5 20h14v-2H5m14-9h-4V3H9v6H5l7 7 7-7Z', upload: 'M9 16h6v-6h4l-7-7-7 7h4m-4 8h14v2H5Z',
    folder: 'M10 4H2v16h20V6H12l-2-2Z', refresh: 'M17.7 6.3A8 8 0 1 0 20 12h-2a6 6 0 1 1-1.8-4.3L13 11h8V3l-3.3 3.3Z',
    search: 'M10 3a7 7 0 1 0 4.9 12l5.4 5.4 1.4-1.4-5.4-5.4A7 7 0 0 0 10 3m0 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10Z',
    close: 'm6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4Z',
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name]} /></svg>;
}
const GROUPS: { id: FileGroup; label: string; description: string }[] = [
  { id: 'recordings', label: 'Drive recordings', description: 'CSV recordings from Drive Logger profiles. Named Data & Logs sessions export from Review.' },
  { id: 'debug', label: 'Debug logs', description: 'Saved service journals, current errors, Hudiy API events, and controller operation reports.' },
  { id: 'controllers', label: 'Controller files', description: 'Firmware libraries and readout images. Uploading saves a file; flashing is a separate action in the controller tools.' },
];

export function FilesTab({ loadCatalog: fetchCatalog = loadCatalog, sendFile: postFile = sendFile,
  initialGroup = 'recordings', initialCollection = 'drive_logs' }: FilesTabProps = {}) {
  const [catalog, setCatalog] = useState<PortalCatalog | null>(null);
  const [group, setGroup] = useState<FileGroup>(initialGroup);
  const [activeCollection, setActiveCollection] = useState(initialCollection);
  const [selectedTarget, setSelectedTarget] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);
  const [pin, setPin] = useState('');
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('date');
  const [showUpload, setShowUpload] = useState(initialGroup === 'controllers');
  const [archive, setArchive] = useState<{ label: string; status: ArchiveJobStatus | null; error: string | null; busy: boolean; url: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const archiveController = useRef<AbortController | null>(null);
  const downloadedArchive = useRef<string | null>(null);
  const archiveLinkRef = useRef<HTMLAnchorElement>(null);
  const requestId = useRef(0);
  const refresh = async () => {
    const request = ++requestId.current; setLoading(true);
    try {
      const data = await fetchCatalog(); if (request !== requestId.current) return;
      setCatalog(data);
      const targets = data.collections.filter(collection => collection.upload);
      setSelectedTarget(previous => targets.some(target => target.id === previous) ? previous : targets[0]?.id || '');
      setActiveCollection(previous => data.collections.some(collection => collection.id === previous) ? previous : data.collections[0]?.id || '');
    } catch (error) {
      if (request === requestId.current) setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Could not load files.' });
    } finally { if (request === requestId.current) setLoading(false); }
  };
  useEffect(() => { void refresh(); return () => { requestId.current++; archiveController.current?.abort(); }; }, [fetchCatalog]);
  useEffect(() => {
    const url = archive?.status?.state === 'ready' ? archive.status.download_url : null;
    if (url && downloadedArchive.current !== url) {
      downloadedArchive.current = url;
      archiveLinkRef.current?.click();
    }
  }, [archive]);
  const startArchive = async (url: string, label: string) => {
    if (archive?.busy) return;
    archiveController.current?.abort();
    const controller = new AbortController(); archiveController.current = controller;
    setArchive({ url, label, status: null, error: null, busy: true });
    try {
      const status = await prepareArchive({ archiveUrl: url, signal: controller.signal,
        onStatus: next => { if (!controller.signal.aborted) setArchive({ url, label, status: next, error: null, busy: true }); } });
      if (!controller.signal.aborted) setArchive({ url, label, status, error: null, busy: false });
    } catch (error) {
      if (!controller.signal.aborted) setArchive(previous => previous ? { ...previous, busy: false,
        error: error instanceof Error ? error.message : 'ZIP preparation failed.' } : null);
    }
  };
  const collections = catalog?.collections || [];
  const groupCollections = collections.filter(collection => collectionGroup(collection) === group);
  const currentCollection = groupCollections.find(collection => collection.id === activeCollection) || groupCollections[0];
  const uploadTargets = collections.filter(collection => collection.upload);
  const currentTarget = uploadTargets.find(target => target.id === selectedTarget);
  const files = useMemo(() => visibleFiles(currentCollection?.files || [], search, sort), [currentCollection, search, sort]);
  const folders = useMemo(() => folderFiles(files, currentCollection?.groups, sort, currentCollection?.kind === 'logs'), [files, currentCollection, sort]);
  const fileRow = (file: PortalFile) => <a className="portal-file-row" href={file.download_url} key={`${currentCollection?.id}:${file.path}`} aria-label={`Download ${file.path}`}>
    <span className="portal-file-type">{file.name.split('.').pop()?.slice(0, 4).toUpperCase()}</span>
    <span className="portal-file-name"><strong>{file.name}</strong><small>{formatDate(file.modified)} · {formatSize(file.size)}</small>{file.path !== file.name && <small className="portal-file-path">{file.path}</small>}</span>
    <span className="portal-download-icon"><Icon name="download" /></span></a>;
  const validation = selectedFile && currentTarget ? validateFile(selectedFile, currentTarget) : null;
  const chooseFile = (file: File | null) => { setSelectedFile(file); setMessage(null); };
  const onFileInput = (event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0] || null);
  const onDrop = (event: DragEvent) => {
    event.preventDefault(); setDragging(false); if (!uploading) chooseFile(event.dataTransfer.files?.[0] || null);
  };
  const upload = async () => {
    if (!selectedFile || !currentTarget || validation || uploading) return;
    setUploading(true); setProgress(0); setMessage(null);
    try {
      const text = await postFile(selectedTarget, selectedFile, pin, setProgress);
      setGroup(collectionGroup(currentTarget));
      setActiveCollection(selectedTarget);
      setSearch('');
      setMessage({ type: 'ok', text }); setSelectedFile(null); if (inputRef.current) inputRef.current.value = '';
      await refresh();
    } catch (error) { setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Upload failed.' }); }
    finally { setUploading(false); }
  };
  const [configurationOpen, setConfigurationOpen] = useState(false);
  const selectGroup = (next: FileGroup) => {
    setConfigurationOpen(false);
    setGroup(next); setSearch(''); setActiveCollection(collections.find(collection => collectionGroup(collection) === next)?.id || '');
  };
  return <section className="file-portal tab-content">
    <header className="portal-header">
      <div className="portal-brand"><span className="portal-brand-icon"><Icon name="folder" /></span><div><h1>Files</h1><p>Recordings, logs & controller libraries</p></div></div>
      <div className="portal-header-actions">
        {catalog?.all_logs_archive_url && <button className="portal-text-button" onClick={() => void startArchive(catalog.all_logs_archive_url!, 'All logs ZIP')} disabled={archive?.busy}><Icon name="download" />All logs ZIP</button>}
        <button className="portal-primary-button portal-upload-open" onClick={() => { selectGroup('controllers'); setShowUpload(true); }} disabled={loading}><Icon name="upload" />Upload file</button>
        <button className="portal-icon-button" onClick={() => { setMessage(null); void refresh(); }} aria-label="Refresh files" disabled={loading}><Icon name="refresh" /></button>
      </div>
    </header>
    {archive && <section className={`portal-archive-status${archive.error ? ' failed' : archive.status?.state === 'ready' ? ' ready' : ''}`} aria-live="polite" aria-atomic="true">
      <div className="portal-archive-status-heading"><strong>{archive.error ? `${archive.label} failed` : archive.status?.state === 'ready' ? `${archive.label} is ready` : `Preparing ${archive.label}`}</strong>
        {archive.busy && <span>{archive.status?.state === 'queued' ? 'Waiting for a worker…' : 'Compressing files…'}</span>}
      </div>
      {archive.busy && <><div className="portal-archive-progress" role="progressbar" aria-label={`${archive.label} preparation`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={archive.status?.percent || 0}><span style={{ width: `${Math.max(0, Math.min(100, archive.status?.percent || 0))}%` }} /></div>
        <div className="portal-archive-details"><span>{formatSize(archive.status?.bytes_processed || 0)} of {formatSize(archive.status?.total_bytes || 0)} · {Math.max(0, Math.min(100, archive.status?.percent || 0))}%</span>{archive.status?.current_file && <span className="portal-archive-file">{archive.status.current_file}</span>}</div></>}
      {archive.error && <div className="portal-archive-result"><span role="alert">{archive.error}</span><button className="portal-primary-button" onClick={() => void startArchive(archive.url, archive.label)}>Retry ZIP</button></div>}
      {archive.status?.state === 'ready' && !archive.error && <a className="portal-bundle-button portal-archive-download" href={archive.status.download_url || undefined}><Icon name="download" />Download ZIP</a>}
      {archive.status?.state === 'ready' && <a ref={archiveLinkRef} className="portal-archive-auto-download" href={archive.status.download_url || undefined} aria-hidden="true" tabIndex={-1} download />}
    </section>}
    <nav className="portal-groups" aria-label="File categories">{GROUPS.map(item => <button key={item.id} aria-pressed={!configurationOpen && group === item.id}
      className={!configurationOpen && group === item.id ? 'active' : ''} onClick={() => selectGroup(item.id)}>{item.label}<span>{collections.filter(c => collectionGroup(c) === item.id).reduce((sum, c) => sum + c.count, 0)}</span></button>)}<button aria-pressed={configurationOpen} className={configurationOpen ? 'active' : ''} onClick={() => setConfigurationOpen(true)}>Configuration</button></nav>
    <div className="portal-scroll pretty-scroll">
      {configurationOpen ? <ConfigUploadPanel /> : <><p className="portal-group-description">{GROUPS.find(item => item.id === group)?.description}</p>
      <div className={`portal-workspace${showUpload && group === 'controllers' ? ' has-upload' : ''}`}>
        <div className="portal-browser">
          <aside className="portal-collections" aria-label="Collections"><span className="portal-field-label">Collections</span>
            {groupCollections.map(collection => <button key={collection.id} aria-pressed={currentCollection?.id === collection.id}
              className={currentCollection?.id === collection.id ? 'active' : ''} onClick={() => { setActiveCollection(collection.id); setSearch(''); }}><Icon name="folder" /><span>{collection.label}<small>{collection.count} {collection.count === 1 ? 'file' : 'files'} · {formatSize(collection.total_size)}</small></span></button>)}
          </aside>
          <article className="portal-card library-card">
            <div className="collection-summary"><div><h2>{currentCollection?.label || 'Files'}</h2><p>{currentCollection?.description || 'Your device files appear here.'}</p></div>
              {currentCollection?.archive_url && <button className="portal-bundle-button" onClick={() => void startArchive(currentCollection.archive_url!, `${currentCollection.label} ZIP`)} disabled={archive?.busy}><Icon name="download" /><span>Collection ZIP</span></button>}
            </div>
            <div className="portal-list-tools"><label className="portal-search"><Icon name="search" /><TouchTextInput touchOnly type="search" aria-label="Search files" placeholder="Search files" value={search} onValueChange={setSearch} /></label>
              <select aria-label="Sort files" value={sort} onChange={event => setSort(event.target.value)}><option value="date">Newest first</option><option value="name">Name A–Z</option><option value="size">Largest first</option></select></div>
            <div className="portal-file-list pretty-scroll" aria-busy={loading}>
              {loading && <div className="portal-empty" role="status">Loading device files…</div>}
              {!loading && !files.length && <div className="portal-empty">{search ? 'No files match this search.' : 'No files in this collection yet.'}</div>}
              {!loading && folders.map(folder => folder.label ? <div className="portal-folder" key={`${currentCollection?.id}:${folder.key}`}>
                <div className="portal-folder-heading"><span><Icon name="folder" /><strong>{folder.label}</strong><small>{folder.files.length} {folder.files.length === 1 ? 'file' : 'files'}</small></span>
                  {folder.archive_url && <button className="portal-bundle-button" onClick={() => void startArchive(folder.archive_url!, `${folder.path} ZIP`)} disabled={archive?.busy} aria-label={`Prepare ${folder.path} ZIP`}><Icon name="download" /><span>Folder ZIP</span></button>}</div>
                <details key={`${currentCollection?.id}:${folder.key}:${!!search}`} open={search ? true : undefined}><summary>Browse files</summary>{folder.files.map(fileRow)}</details>
              </div> : folder.files.map(fileRow))}
            </div>
            {!loading && <p className="portal-list-count">{files.length} of {currentCollection?.count || 0} {currentCollection?.count === 1 ? 'file' : 'files'}</p>}
          </article>
        </div>
        {showUpload && group === 'controllers' && <article className="portal-card upload-card">
          <div className="portal-card-heading"><span className="portal-card-icon"><Icon name="upload" /></span><h2>Upload a file</h2><button className="portal-icon-button" aria-label="Close upload panel" onClick={() => setShowUpload(false)} disabled={uploading}><Icon name="close" /></button></div>
          <label className="portal-field-label" htmlFor="firmware-target">Save to collection</label>
          <select id="firmware-target" className="portal-select" value={selectedTarget} disabled={uploading || loading}
            onChange={event => { setSelectedTarget(event.target.value); chooseFile(null); if (inputRef.current) inputRef.current.value = ''; }}>{uploadTargets.map(target => <option value={target.id} key={target.id}>{target.label}</option>)}</select>
          <button type="button" disabled={uploading || !currentTarget} className={`portal-drop-zone${dragging ? ' dragging' : ''}`} onClick={() => inputRef.current?.click()}
            onDragOver={event => { event.preventDefault(); if (!uploading) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
            <Icon name="upload" /><strong>{selectedFile?.name || 'Choose or drop a file'}</strong><span>{selectedFile ? formatSize(selectedFile.size) : `${currentTarget?.extensions.join(', ') || 'Configured types'} · up to ${formatSize(currentTarget?.max_size || 0)}`}</span></button>
          <input ref={inputRef} className="portal-file-input" type="file" accept={currentTarget?.extensions.join(',')} onChange={onFileInput} disabled={uploading} />
          {catalog?.pin_required && <label className="portal-pin-label">Upload PIN<TouchTextInput touchOnly className="portal-pin" type="password" aria-label="Upload PIN" inputMode="numeric" autoComplete="off" value={pin} disabled={uploading} onValueChange={setPin} /></label>}
          {validation && <p className="portal-validation" role="alert">{validation}</p>}
          {uploading && <div className="portal-progress" role="progressbar" aria-label="File upload" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div>}
          <button className="portal-primary-button" disabled={!selectedFile || uploading || !!validation || !selectedTarget || (catalog?.pin_required && !pin)} onClick={() => void upload()}>{uploading ? `Uploading ${progress}%` : 'Validate & save'}</button>
          <p className="portal-safety-note">Firmware is checked for the selected target before saving. Uploading does not start a flash.</p>
        </article>}
      </div></>}
    </div>
    {message && <div className={`portal-message ${message.type}`} role={message.type === 'error' ? 'alert' : 'status'}><span>{message.text}</span><button className="portal-icon-button" aria-label="Dismiss message" onClick={() => setMessage(null)}><Icon name="close" /></button></div>}
  </section>;
}
