import { useEffect, useRef, useState } from 'react';
import type { ManagementApi } from './ManagementApp';
import './rnseTestPattern.css';

export function RnseTestPattern({ close, notice }: { close: () => void; notice: string }) {
  const [full, setFull] = useState(!!document.fullscreenElement);
  const [error, setError] = useState('');
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const change = () => setFull(!!document.fullscreenElement);
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); close(); } };
    document.addEventListener('fullscreenchange', change);
    document.addEventListener('keydown', key);
    const previous = window.hudiy?.onGoBack;
    const back = () => { close(); return true; };
    if (window.hudiy) window.hudiy.onGoBack = back;
    return () => { document.removeEventListener('fullscreenchange', change); document.removeEventListener('keydown', key); if (window.hudiy?.onGoBack === back) window.hudiy.onGoBack = previous; };
  }, [close]);
  return <div ref={root} className="rnse-test-pattern" role="dialog" aria-modal="true" aria-label="RNS-E test pattern">
    <img src="/static/rnse-adc-testpattern.png" width="800" height="480" draggable={false} alt="ADC calibration pattern, 800 by 480 pixels, unscaled" />
    <div className="rnse-pattern-actions"><span>{error || notice}</span>{!full && <button onClick={() => { void root.current?.requestFullscreen?.().catch(() => setError('This WebView cannot hide the taskbar. Image remains unscaled; scroll to inspect it.')); }}>Fullscreen</button>}<button autoFocus onClick={close}>Back to sliders</button></div>
  </div>;
}

/** Request browser fullscreen in the button gesture; native Hudiy viewer is preferred on the Pi. */
export function openPatternWindow(api: ManagementApi, pin: string) {
  return api<{ running: boolean }>('/test-pattern/open', { method: 'POST', headers: { 'X-Hudiy-Management': '1', ...(pin ? { 'X-Hudiy-Pin': pin } : {}) } });
}
