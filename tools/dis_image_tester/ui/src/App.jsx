import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import './App.css';

// --- Constants ---
const API_BASE = 'http://localhost:8000';

const INITIAL_PARAMS = {
  contrast: 1.4,
  sharpen: 1.5,
  dither: 'fs',
  invert: false,
  no_enhance: false,
  bg_fill: 'black',
  grayscale_mode: 'smart',
  brightness: 1.0,
  gamma: 2.2,
  black_floor: 45,
  boldness: 0.0,
  diffusion: 0.85,
  width: 64,
  height: 48,
  max_frames: 300,
};

// --- Helper Hook: Debounce ---
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

// --- Components ---

const ControlRow = ({ label, children }) => (
  <div className="control-row">
    <label>{label}</label>
    <div className="control-input">{children}</div>
  </div>
);

const SliderControl = ({ label, value, min, max, step, onChange }) => (
  <div className="control-row">
    <label>{label}</label>
    <div className="control-input">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
      />
      <input
        type="number"
        className="num-entry"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => {
          const val = parseFloat(e.target.value);
          if (!isNaN(val)) onChange(val);
        }}
      />
    </div>
  </div>
);

const MediaCard = ({
  filename,
  isGif,
  params,
  isActive,
  onSelect,
  showOriginalSideBySide,
}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(true);
  const [scrubFrame, setScrubFrame] = useState(0);
  const [peekOriginal, setPeekOriginal] = useState(false);
  const abortControllerRef = useRef(null);

  useEffect(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setLoading(true);
    fetch(`${API_BASE}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, ...params }),
      signal: controller.signal,
    })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP error ${r.status}`);
        return r.json();
      })
      .then(res => {
        setData(res);
        setLoading(false);
        // Reset scrub frame if outside new frame count
        if (res.frames && res.frames.length > 0) {
          setScrubFrame(prev => (prev < res.frames.length ? prev : 0));
        }
      })
      .catch(err => {
        if (err.name !== 'AbortError') {
          console.error(`Error processing ${filename}:`, err);
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [filename, params]);

  const totalFrames = data?.frames?.length || data?.frame_count || 1;

  const currentDisplaySrc = useMemo(() => {
    if (!data) return '';
    if (peekOriginal) return data.original;
    if (!isGif) return data.processed;

    // For GIF:
    if (isPlaying) {
      return data.processed; // Native animated GIF base64
    }
    // Paused: show selected frame
    if (data.frames && data.frames[scrubFrame]) {
      return data.frames[scrubFrame];
    }
    return data.first_frame || data.processed;
  }, [data, isGif, isPlaying, scrubFrame, peekOriginal]);

  return (
    <div
      className={`media-card glass fade-in ${isActive ? 'active-card' : ''} ${
        isGif ? 'is-gif-card' : ''
      }`}
      onClick={onSelect}
    >
      <div className="card-top-bar">
        <span className={`media-type-badge ${isGif ? 'badge-gif' : 'badge-img'}`}>
          {isGif ? `🎬 GIF • ${totalFrames}f @ ${data?.fps || 10}fps` : '🖼️ IMAGE'}
        </span>
        {isGif && (
          <div className="gif-playback-pill" onClick={e => e.stopPropagation()}>
            <button
              className={`pill-btn ${isPlaying ? 'active' : ''}`}
              title={isPlaying ? 'Pause animation' : 'Play animation'}
              onClick={() => setIsPlaying(!isPlaying)}
            >
              {isPlaying ? '⏸ Pause' : '▶ Play'}
            </button>
            <button
              className={`pill-btn peek-btn ${peekOriginal ? 'active' : ''}`}
              title="Hold or toggle to compare with original"
              onMouseDown={() => setPeekOriginal(true)}
              onMouseUp={() => setPeekOriginal(false)}
              onMouseLeave={() => setPeekOriginal(false)}
              onClick={() => setPeekOriginal(!peekOriginal)}
            >
              Peek
            </button>
          </div>
        )}
      </div>

      <div className={`screen-wrapper ${showOriginalSideBySide ? 'side-by-side' : ''}`}>
        {showOriginalSideBySide && data?.original && (
          <div className="screen-frame original-frame">
            <span className="screen-sublabel">Original</span>
            <img src={data.original} alt={`${filename} original`} className="screen-img original-img" />
          </div>
        )}

        <div className="screen-frame">
          {showOriginalSideBySide && <span className="screen-sublabel">Processed DIS</span>}
          {loading && <div className="loading-spinner-overlay"><div className="spinner" /></div>}
          {currentDisplaySrc ? (
            <img
              src={currentDisplaySrc}
              alt={filename}
              className="pixelated screen-img"
            />
          ) : (
            <div className="card-skeleton">Processing...</div>
          )}
        </div>
      </div>

      {isGif && data?.frames && data.frames.length > 1 && (
        <div className="scrubber-bar" onClick={e => e.stopPropagation()}>
          <button
            className="step-btn"
            title="Previous frame"
            onClick={() => {
              setIsPlaying(false);
              setScrubFrame(prev => Math.max(0, prev - 1));
            }}
          >
            ⏮
          </button>

          <input
            type="range"
            className="frame-slider"
            min={0}
            max={totalFrames - 1}
            value={scrubFrame}
            onChange={e => {
              setIsPlaying(false);
              setScrubFrame(parseInt(e.target.value, 10));
            }}
          />

          <button
            className="step-btn"
            title="Next frame"
            onClick={() => {
              setIsPlaying(false);
              setScrubFrame(prev => Math.min(totalFrames - 1, prev + 1));
            }}
          >
            ⏭
          </button>

          <span className="frame-counter">
            {scrubFrame + 1} / {totalFrames}
          </span>
        </div>
      )}

      <div className="image-info">
        <div className="filename" title={filename}>{filename}</div>
        <div className="meta-tag">
          {params.width}x{params.height} • {params.dither.toUpperCase()}
        </div>
      </div>
    </div>
  );
};

export default function App() {
  const [media, setMedia] = useState({ images: [], gifs: [], all: [] });
  const [filter, setFilter] = useState('all'); // 'all' | 'image' | 'gif'
  const [search, setSearch] = useState('');
  const [params, setParams] = useState(INITIAL_PARAMS);
  const [activeFilename, setActiveFilename] = useState('');
  const [activeConfig, setActiveConfig] = useState(null);
  const [activeTab, setActiveTab] = useState('snippet'); // 'snippet' | 'python' | 'json' | 'egg'
  const [showOriginals, setShowOriginals] = useState(false);
  const [copiedKey, setCopiedKey] = useState(null);
  const fileInputRef = useRef(null);

  const debouncedParams = useDebounce(params, 150);

  const loadMediaList = useCallback(() => {
    fetch(`${API_BASE}/api/images`)
      .then(r => r.json())
      .then(res => {
        setMedia(res);
        if (!activeFilename) {
          if (res.gifs && res.gifs.length > 0) {
            setActiveFilename(res.gifs[0]);
          } else if (res.images && res.images.length > 0) {
            setActiveFilename(res.images[0]);
          }
        }
      })
      .catch(err => console.error('Failed to load media items', err));
  }, [activeFilename]);

  useEffect(() => {
    loadMediaList();
  }, [loadMediaList]);

  // Fetch active config preview whenever active file or parameters change
  useEffect(() => {
    if (!activeFilename) return;
    const isGif = activeFilename.toLowerCase().endsWith('.gif');

    fetch(`${API_BASE}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: activeFilename, ...debouncedParams }),
    })
      .then(r => r.json())
      .then(res => {
        const rawJson = res.config_json;
        const processedJson = typeof rawJson === 'string' ? JSON.parse(rawJson) : rawJson;

        setActiveConfig({
          isGif: res.is_gif,
          filename: activeFilename,
          string: res.config_string,
          json: JSON.stringify(processedJson, null, 2),
          snippet: JSON.stringify(res.config_snippet, null, 2),
          eggSnippet: res.egg_snippet ? JSON.stringify(res.egg_snippet, null, 2) : '',
        });

        // Set default tab based on media type
        if (isGif && activeTab === 'snippet') {
          setActiveTab('egg');
        }
      })
      .catch(err => console.error('Error fetching active preview config:', err));
  }, [activeFilename, debouncedParams]);

  const updateParam = (key, val) => {
    setParams(prev => ({ ...prev, [key]: val }));
  };

  const handleReset = () => {
    setParams(INITIAL_PARAMS);
  };

  const handleFileUpload = e => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, data: reader.result }),
      })
        .then(r => r.json())
        .then(res => {
          loadMediaList();
          setActiveFilename(res.filename);
          if (res.type === 'gif') setFilter('gif');
        })
        .catch(err => alert(`Upload failed: ${err.message}`));
    };
    reader.readAsDataURL(file);
  };

  const copyToClipboard = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  // Filter items
  const filteredItems = useMemo(() => {
    let items = [];
    if (filter === 'image') {
      items = media.images.map(f => ({ filename: f, type: 'image' }));
    } else if (filter === 'gif') {
      items = media.gifs.map(f => ({ filename: f, type: 'gif' }));
    } else {
      items = media.all || [];
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter(i => i.filename.toLowerCase().includes(q));
    }
    return items;
  }, [media, filter, search]);

  const isCurrentActiveGif = activeFilename.toLowerCase().endsWith('.gif');

  return (
    <div className="app-container">
      {/* Sidebar Controls */}
      <aside className="sidebar glass">
        <header>
          <h1>
            DIS Image & GIF <span className="accent">Tester</span>
          </h1>
          <p className="subtitle">Real-time DIS pixelated display preview</p>
        </header>

        <section className="controls">
          <h3>Enhancement</h3>
          <SliderControl label="Contrast" value={params.contrast} min={0} max={3} step={0.1} onChange={v => updateParam('contrast', v)} />
          <SliderControl label="Sharpen" value={params.sharpen} min={0} max={5} step={0.1} onChange={v => updateParam('sharpen', v)} />
          <SliderControl label="Brightness" value={params.brightness} min={0} max={3} step={0.1} onChange={v => updateParam('brightness', v)} />
          <SliderControl label="Gamma" value={params.gamma} min={0.1} max={4} step={0.1} onChange={v => updateParam('gamma', v)} />

          <div className="divider" />

          <h3>Thresholds</h3>
          <SliderControl label="Black Floor" value={params.black_floor} min={0} max={255} step={1} onChange={v => updateParam('black_floor', v)} />
          <SliderControl label="Boldness" value={params.boldness} min={0} max={5} step={0.1} onChange={v => updateParam('boldness', v)} />

          <div className="divider" />

          <h3>Algorithms</h3>
          <ControlRow label="Resolution">
            <select
              value={`${params.width || 64}x${params.height || 48}`}
              onChange={e => {
                const [w, h] = e.target.value.split('x').map(Number);
                setParams(prev => ({ ...prev, width: w, height: h }));
              }}
            >
              <option value="64x48">64x48 (DIS Native)</option>
              <option value="128x96">128x96 (High Res)</option>
            </select>
          </ControlRow>
          <ControlRow label="Dither">
            <select value={params.dither} onChange={e => updateParam('dither', e.target.value)}>
              <option value="fs">Floyd-Steinberg</option>
              <option value="atkinson">Atkinson</option>
              <option value="none">None (Threshold)</option>
            </select>
          </ControlRow>
          {params.dither === 'atkinson' && (
            <SliderControl label="Diffusion" value={params.diffusion} min={0} max={1} step={0.05} onChange={v => updateParam('diffusion', v)} />
          )}
          <ControlRow label="Grayscale">
            <select value={params.grayscale_mode} onChange={e => updateParam('grayscale_mode', e.target.value)}>
              <option value="smart">Smart (Saturation Aware)</option>
              <option value="max">Max Channel</option>
              <option value="balanced">Balanced</option>
              <option value="weighted">Weighted (Rec.709)</option>
            </select>
          </ControlRow>
          <ControlRow label="BG Fill">
            <select value={params.bg_fill} onChange={e => updateParam('bg_fill', e.target.value)}>
              <option value="black">Black</option>
              <option value="white">White</option>
              <option value="edge">Edge Smear</option>
              <option value="blur">Blurred Background</option>
            </select>
          </ControlRow>

          <div className="divider" />

          <h3>Toggles</h3>
          <ControlRow label="Invert Colors">
            <input type="checkbox" checked={params.invert} onChange={e => updateParam('invert', e.target.checked)} />
          </ControlRow>
          <ControlRow label="Bypass Enhancements">
            <input type="checkbox" checked={params.no_enhance} onChange={e => updateParam('no_enhance', e.target.checked)} />
          </ControlRow>
        </section>

        <footer>
          <button className="reset-btn" onClick={handleReset}>
            Reset to Defaults
          </button>
        </footer>
      </aside>

      {/* Main Viewer Area */}
      <main className="viewer">
        {/* Top Control & Filter Bar */}
        <section className="top-filter-bar glass">
          <div className="filter-group">
            <button
              className={`filter-pill ${filter === 'all' ? 'active' : ''}`}
              onClick={() => setFilter('all')}
            >
              All Media ({media.all?.length || 0})
            </button>
            <button
              className={`filter-pill ${filter === 'gif' ? 'active' : ''}`}
              onClick={() => setFilter('gif')}
            >
              🎬 GIFs ({media.gifs?.length || 0})
            </button>
            <button
              className={`filter-pill ${filter === 'image' ? 'active' : ''}`}
              onClick={() => setFilter('image')}
            >
              🖼️ Images ({media.images?.length || 0})
            </button>
          </div>

          <div className="search-and-actions">
            <input
              type="text"
              className="search-input"
              placeholder="Search filename..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />

            <button
              className={`action-btn ${showOriginals ? 'active-toggle' : ''}`}
              onClick={() => setShowOriginals(!showOriginals)}
              title="Show original full-color side-by-side with DIS bitmap"
            >
              {showOriginals ? 'Hide Originals' : 'Compare Originals'}
            </button>

            <button
              className="action-btn upload-btn"
              onClick={() => fileInputRef.current?.click()}
              title="Upload an image or animated GIF to test"
            >
              + Upload File
            </button>
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              accept=".gif,.png,.jpg,.jpeg,.webp"
              onChange={handleFileUpload}
            />
          </div>
        </section>

        {/* Dynamic Config Output Panel */}
        <section className="config-box glass">
          <div className="config-header">
            <div className="config-title-row">
              <h3>Configuration Output</h3>
              {activeFilename && (
                <span className="active-file-indicator">
                  Target: <strong>{activeFilename}</strong> {isCurrentActiveGif ? '(Animated GIF)' : '(Static Image)'}
                </span>
              )}
            </div>

            <div className="config-tabs-and-copy">
              <div className="tab-pill-group">
                {isCurrentActiveGif && (
                  <button
                    className={`tab-pill ${activeTab === 'egg' ? 'active' : ''}`}
                    onClick={() => setActiveTab('egg')}
                  >
                    Easter Egg (eggs.json)
                  </button>
                )}
                <button
                  className={`tab-pill ${activeTab === 'python' ? 'active' : ''}`}
                  onClick={() => setActiveTab('python')}
                >
                  {isCurrentActiveGif ? 'Python load_gif()' : 'Python process_image()'}
                </button>
                <button
                  className={`tab-pill ${activeTab === 'snippet' ? 'active' : ''}`}
                  onClick={() => setActiveTab('snippet')}
                >
                  Cover Art (config.json)
                </button>
                <button
                  className={`tab-pill ${activeTab === 'json' ? 'active' : ''}`}
                  onClick={() => setActiveTab('json')}
                >
                  JSON Args
                </button>
              </div>

              <button
                className="copy-btn"
                onClick={() => {
                  let textToCopy = '';
                  if (activeTab === 'egg') textToCopy = activeConfig?.eggSnippet || '';
                  else if (activeTab === 'python') textToCopy = activeConfig?.string || '';
                  else if (activeTab === 'snippet') textToCopy = activeConfig?.snippet || '';
                  else textToCopy = activeConfig?.json || '';

                  copyToClipboard(textToCopy, activeTab);
                }}
              >
                {copiedKey === activeTab ? '✓ Copied!' : 'Copy Code'}
              </button>
            </div>
          </div>

          <div className="code-container">
            <pre className="code-block">
              <code>
                {activeTab === 'egg' && (activeConfig?.eggSnippet || 'Select a GIF to generate Easter Egg config')}
                {activeTab === 'python' && (activeConfig?.string || 'Loading Python call...')}
                {activeTab === 'snippet' && (activeConfig?.snippet || 'Loading config snippet...')}
                {activeTab === 'json' && (activeConfig?.json || 'Loading JSON...')}
              </code>
            </pre>
          </div>
        </section>

        {/* Media Grid */}
        <div className="image-grid">
          {filteredItems.map(item => (
            <MediaCard
              key={item.filename}
              filename={item.filename}
              isGif={item.type === 'gif'}
              params={debouncedParams}
              isActive={activeFilename === item.filename}
              onSelect={() => setActiveFilename(item.filename)}
              showOriginalSideBySide={showOriginals}
            />
          ))}

          {filteredItems.length === 0 && (
            <div className="empty-state glass">
              <p>No media files match your filter or search query.</p>
              <button
                className="upload-btn"
                onClick={() => fileInputRef.current?.click()}
              >
                Upload an Image or GIF
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
