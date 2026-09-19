import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from 'react';

interface PortalFile {
  name: string;
  path: string;
  size: number;
  modified: number;
  download_url: string;
}

interface PortalCollection {
  id: string;
  label: string;
  description: string;
  kind: 'firmware' | 'logs' | 'readouts';
  upload: boolean;
  extensions: string[];
  max_size: number;
  count: number;
  total_size: number;
  archive_url: string | null;
  files: PortalFile[];
}

interface PortalCatalog {
  pin_required: boolean;
  all_logs_archive_url: string | null;
  collections: PortalCollection[];
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(bytes < 10 * 1024 ** 2 ? 1 : 0)} MB`;
};

const formatDate = (timestamp: number) => new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
}).format(new Date(timestamp * 1000));

const DownloadIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 20h14v-2H5m14-9h-4V3H9v6H5l7 7 7-7Z" /></svg>;
const UploadIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 16h6v-6h4l-7-7-7 7h4m-4 8h14v2H5Z" /></svg>;
const FolderIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H2v16h20V6H12l-2-2Z" /></svg>;
const RefreshIcon = () => <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.7 6.3A8 8 0 1 0 20 12h-2a6 6 0 1 1-1.8-4.3L13 11h8V3l-3.3 3.3Z" /></svg>;

export function FilesTab() {
  const [catalog, setCatalog] = useState<PortalCatalog | null>(null);
  const [selectedTarget, setSelectedTarget] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [activeCollection, setActiveCollection] = useState('drive_logs');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<{ type: 'ok' | 'error'; text: string } | null>(null);
  const [pin, setPin] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/files');
      if (!response.ok) throw new Error(`Portal request failed (${response.status})`);
      const data: PortalCatalog = await response.json();
      setCatalog(data);
      const targets = data.collections.filter(collection => collection.upload);
      setSelectedTarget(previous => targets.some(target => target.id === previous)
        ? previous : (targets[0]?.id || ''));
      setActiveCollection(previous => data.collections.some(collection => collection.id === previous)
        ? previous : (data.collections[0]?.id || ''));
      setMessage(null);
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Could not load files.' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void refresh(); }, []);

  const uploadTargets = useMemo(
    () => catalog?.collections.filter(collection => collection.upload) || [],
    [catalog]
  );
  const currentTarget = uploadTargets.find(target => target.id === selectedTarget);
  const browseCollections = catalog?.collections || [];
  const currentCollection = browseCollections.find(collection => collection.id === activeCollection);

  const chooseFile = (file: File | null) => {
    setSelectedFile(file);
    setMessage(null);
  };

  const onFileInput = (event: ChangeEvent<HTMLInputElement>) => chooseFile(event.target.files?.[0] || null);
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0] || null);
  };

  const upload = () => {
    if (!selectedFile || !selectedTarget || uploading) return;
    const form = new FormData();
    form.append('file', selectedFile);
    setUploading(true);
    setUploadProgress(0);
    setMessage(null);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/files/upload/${encodeURIComponent(selectedTarget)}`);
    if (pin) xhr.setRequestHeader('X-Hudiy-Pin', pin);
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) setUploadProgress(Math.round(event.loaded / event.total * 100));
    };
    xhr.onload = () => {
      setUploading(false);
      let body: { message?: string; error?: string } = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* use fallback below */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        setMessage({ type: 'ok', text: body.message || 'Upload complete.' });
        setSelectedFile(null);
        if (inputRef.current) inputRef.current.value = '';
        void refresh();
      } else {
        setMessage({ type: 'error', text: body.error || `Upload failed (${xhr.status}).` });
      }
    };
    xhr.onerror = () => {
      setUploading(false);
      setMessage({ type: 'error', text: 'Connection lost during upload.' });
    };
    xhr.send(form);
  };

  return (
    <section className="file-portal tab-content">
      <header className="portal-header">
        <div>
          <span className="portal-eyebrow">DEVICE STORAGE</span>
          <h1>Files</h1>
          <p>Move firmware, recordings, and diagnostics without a laptop.</p>
        </div>
        <button className="portal-icon-button" onClick={() => void refresh()} aria-label="Refresh files" disabled={loading}>
          <RefreshIcon />
        </button>
      </header>

      <div className="portal-scroll pretty-scroll">
        <div className="portal-grid">
          <article className="portal-card upload-card">
            <div className="portal-card-heading">
              <span className="portal-card-icon"><UploadIcon /></span>
              <div><h2>Send firmware</h2><p>Choose the controller this artifact belongs to.</p></div>
            </div>

            <label className="portal-field-label" htmlFor="firmware-target">Target</label>
            <select id="firmware-target" className="portal-select" value={selectedTarget}
              onChange={event => { setSelectedTarget(event.target.value); chooseFile(null); }}>
              {uploadTargets.map(target => <option value={target.id} key={target.id}>{target.label}</option>)}
            </select>

            <button type="button" className={`portal-drop-zone${dragging ? ' dragging' : ''}`}
              onClick={() => inputRef.current?.click()}
              onDragOver={event => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)} onDrop={onDrop}>
              <span className="drop-icon"><UploadIcon /></span>
              <strong>{selectedFile ? selectedFile.name : 'Choose a firmware file'}</strong>
              <span>{selectedFile ? formatSize(selectedFile.size)
                : `${currentTarget?.extensions.join(', ') || 'Configured types'} • up to ${formatSize(currentTarget?.max_size || 0)}`}</span>
            </button>
            <input ref={inputRef} className="portal-file-input" type="file"
              accept={currentTarget?.extensions.join(',')} onChange={onFileInput} />

            {catalog?.pin_required && <input className="portal-pin" type="password" inputMode="numeric"
              placeholder="Portal PIN" value={pin} onChange={event => setPin(event.target.value)} />}

            {uploading && <div className="portal-progress" aria-label={`Upload ${uploadProgress}%`}>
              <span style={{ width: `${uploadProgress}%` }} />
            </div>}
            <button className="portal-primary-button" disabled={!selectedFile || uploading || !selectedTarget} onClick={upload}>
              {uploading ? `Uploading ${uploadProgress}%` : 'Validate & save'}
            </button>
            <p className="portal-safety-note">Uploading only adds the file to the library. It never starts a flash.</p>
          </article>

          <article className="portal-card library-card">
            <div className="portal-card-heading">
              <span className="portal-card-icon"><FolderIcon /></span>
              <div className="portal-library-title"><h2>Get files</h2><p>Recordings, service errors, flash reports, and readouts.</p></div>
              {catalog?.all_logs_archive_url && <a className="portal-all-logs" href={catalog.all_logs_archive_url}>
                <DownloadIcon /> All logs
              </a>}
            </div>

            <div className="collection-chips pretty-scroll" role="tablist">
              {browseCollections.map(collection => <button key={collection.id}
                className={`collection-chip${activeCollection === collection.id ? ' active' : ''}`}
                onClick={() => setActiveCollection(collection.id)} role="tab">
                {collection.label}<span>{collection.count}</span>
              </button>)}
            </div>

            <div className="collection-summary">
              <div><strong>{currentCollection?.label}</strong><span>{currentCollection?.description}</span></div>
              {currentCollection?.archive_url && <a className="portal-bundle-button" href={currentCollection.archive_url}>
                <DownloadIcon /> Download all
              </a>}
            </div>

            <div className="portal-file-list pretty-scroll">
              {loading && <div className="portal-empty">Scanning device storage…</div>}
              {!loading && !currentCollection?.files.length && <div className="portal-empty">No files in this collection yet.</div>}
              {currentCollection?.files.map(file => <a className="portal-file-row" href={file.download_url} key={`${activeCollection}:${file.path}`}>
                <span className="portal-file-type">{file.name.split('.').pop()?.slice(0, 4).toUpperCase()}</span>
                <span className="portal-file-name"><strong>{file.name}</strong><small>{file.path !== file.name ? file.path : formatDate(file.modified)}</small></span>
                <span className="portal-file-meta"><small>{formatDate(file.modified)}</small><strong>{formatSize(file.size)}</strong></span>
                <span className="portal-download-icon"><DownloadIcon /></span>
              </a>)}
            </div>
          </article>
        </div>
        {message && <div className={`portal-message ${message.type}`} role="status">{message.text}</div>}
      </div>
    </section>
  );
}
