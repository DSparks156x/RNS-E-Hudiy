import React, { useState, useEffect, useCallback } from 'react';
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
  height: 48
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

const ImageCard = ({ filename, params }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename, ...params })
    })
      .then(r => r.json())
      .then(res => {
        setData(res);
        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setLoading(false);
      });
  }, [filename, params]);

  if (!data && loading) return <div className="image-card loading">Loading...</div>;
  if (!data) return null;

  return (
    <div className="image-card glass fade-in">
      <div className="image-container">
        <div className="image-label">Processed ({params.width || 64}x{params.height || 48})</div>
        <img 
          src={data.processed} 
          alt={filename} 
          className="pixelated" 
        />
      </div>
      <div className="image-info">
        <div className="filename">{filename}</div>
      </div>
    </div>
  );
};

function App() {
  const [images, setImages] = useState([]);
  const [params, setParams] = useState(INITIAL_PARAMS);
  const [configStrings, setConfigStrings] = useState({ string: '', json: '', snippet: '' });
  
  const debouncedParams = useDebounce(params, 150);

  useEffect(() => {
    fetch(`${API_BASE}/api/images`)
      .then(r => r.json())
      .then(res => setImages(res.images || []))
      .catch(err => console.error("Failed to load images", err));
  }, []);

  // Update config preview when debounced params change
  useEffect(() => {
    if (images.length > 0) {
      fetch(`${API_BASE}/api/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: images[0], ...debouncedParams })
      })
        .then(r => r.json())
        .then(res => {
          const rawJson = res.config_json;
          // Ensure we don't double-stringify if the server returned a string
          const processedJson = typeof rawJson === 'string' ? JSON.parse(rawJson) : rawJson;

          setConfigStrings({ 
            string: res.config_string, 
            json: JSON.stringify(processedJson, null, 2),
            snippet: JSON.stringify(res.config_snippet, null, 2)
          });
        });
    }
  }, [debouncedParams, images]);

  const updateParam = (key, val) => {
    setParams(prev => ({ ...prev, [key]: val }));
  };

  const handleReset = () => {
    setParams(INITIAL_PARAMS);
  };

  return (
    <div className="app-container">
      <aside className="sidebar glass">
        <header>
          <h1>DIS Image <span className="accent">Tester</span></h1>
          <p className="subtitle">Real-time processing preview</p>
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
            <select value={`${params.width || 64}x${params.height || 48}`} onChange={e => {
              const [w, h] = e.target.value.split('x').map(Number);
              setParams(prev => ({ ...prev, width: w, height: h }));
            }}>
              <option value="64x48">64x48 (Default)</option>
              <option value="128x96">128x96</option>
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

          <ControlRow label="Invert">
            <input type="checkbox" checked={params.invert} onChange={e => updateParam('invert', e.target.checked)} />
          </ControlRow>
          <ControlRow label="Bypass All">
            <input type="checkbox" checked={params.no_enhance} onChange={e => updateParam('no_enhance', e.target.checked)} />
          </ControlRow>
        </section>

        <footer>
          <button className="reset-btn" onClick={handleReset}>Reset to Defaults</button>
        </footer>
      </aside>

      <main className="viewer">
        <section className="config-box glass">
          <div className="config-header">
            <h3>Configuration Output</h3>
            <div className="button-group">
              <button className="copy-btn secondary" onClick={() => navigator.clipboard.writeText(configStrings.string)}>Copy Python Call</button>
              <button className="copy-btn" onClick={() => navigator.clipboard.writeText(configStrings.json)}>Copy for Config Editor</button>
            </div>
          </div>
          <details open>
            <summary>View JSON Arguments</summary>
            <pre className="code-block"><code>{configStrings.json || 'Loading...'}</code></pre>
          </details>
        </section>

        <div className="image-grid">
          {images.map(img => (
            <ImageCard key={img} filename={img} params={debouncedParams} />
          ))}
        </div>
      </main>
    </div>
  );
}

export default App;
