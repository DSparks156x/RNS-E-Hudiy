import React, { useEffect, useId, useState } from 'react';
import samples from './navigation-examples.json';
import './navigation-showcase.css';

export function NavigationShowcase() {
  const [playing, setPlaying] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [selected, setSelected] = useState(0);
  const [cycle, setCycle] = useState(0);
  const selectId = useId();
  const sample = samples[selected];
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => { if (preference.matches) setPlaying(false); };
    preference.addEventListener('change', onChange);
    return () => preference.removeEventListener('change', onChange);
  }, []);
  const choose = index => { setPlaying(false); setSelected(index); };
  const play = () => { setSelected(0); setCycle(value => value + 1); setPlaying(true); };
  return <div className="navigation-showcase">
    <p className="nav-showcase-intro">The same maneuvers through both renderers. Straight at 1.2 km, left and right turns, ramps, forks, U-turns and roundabout exits. Distance changes with the maneuver; watch the approach bar fill as a turn gets closer.</p>
    <div className="nav-preview-pair">
      {['stock', 'bitmap'].map(style => <figure key={style}>
        <h3>{style === 'stock' ? 'Stock icons' : 'High-resolution bitmap'}</h3>
        <div className="nav-screen-surround"><div className="nav-screen-frame"><img key={`${style}-${cycle}-${playing}`} src={`./media/${playing ? `nav-showcase-${style}.gif` : sample.images[style]}`} alt={playing ? `${style === 'stock' ? 'Stock-preferred' : 'Bitmap'} navigation: animated sequence of ${samples.length} maneuvers and distances.` : `${sample.label}, ${style === 'stock' ? 'stock-preferred' : 'high-resolution bitmap'} navigation${style === 'stock' && sample.stock_fallback ? ', using bitmap fallback' : ''}.`} width="512" height="384"/></div></div>
        <figcaption>{style === 'stock' ? 'Captured cluster glyphs and the native approach bar. No numeric distance column. Unmapped maneuvers use bitmap artwork.' : 'Project maneuver artwork at native resolution, numeric distance and the same native approach bar.'}</figcaption>
      </figure>)}
    </div>
    <div className="nav-demo-controls">
      <button className="nav-demo-play" type="button" onClick={playing ? () => setPlaying(false) : play} aria-label={playing ? 'Stop navigation animation and inspect a still' : 'Play all navigation examples'}>{playing ? 'Ⅱ Inspect a still' : '▷ Play all examples'}</button>
      <label htmlFor={selectId}>Inspect a maneuver<select id={selectId} value={selected} onChange={event => choose(Number(event.target.value))}>{samples.map((entry, index) => <option key={entry.id} value={index}>{entry.label}</option>)}</select></label>
      <div className="nav-demo-step"><button type="button" aria-label="Previous navigation example" onClick={() => choose((selected + samples.length - 1) % samples.length)}>←</button><button type="button" aria-label="Next navigation example" onClick={() => choose((selected + 1) % samples.length)}>→</button></div>
    </div>
    <p className="nav-demo-state" aria-live="polite">{playing ? `Looping all ${samples.length} examples. Choose a maneuver to compare its still frames.` : `${sample.label}. ${sample.bar_visible ? 'Inside the 300 m approach-bar range.' : 'Outside the 300 m approach-bar range; bar hidden.'}${sample.stock_fallback ? ' This maneuver has no reviewed stock mapping, so Stock icons uses the bitmap fallback.' : ''}`}</p>
    <div className="nav-distance-notes">
      <div><strong>1.2 km: straight, no bar</strong><p>This is beyond the default 500 m approach-switch threshold. You can still open Navigation manually. Bitmap mode shows 1.2 km; stock mode keeps its distance column empty.</p></div>
      <div><strong>500 m: page switching</strong><p>The approach threshold controls when Navigation stays in front. It does not set the bar range; this left-turn example still has no bar.</p></div>
      <div><strong>250 m → 30 m: bar fills</strong><p>The separate 300 m bar range controls progress. Both styles use the same captured bar glyphs; closer means more fill.</p></div>
    </div>
    <p className="nav-render-note">Synthetic route updates rendered by the production DIS apps, not a road recording. Native center area: 128 × 96 pixels, enlarged without smoothing. Roundabout examples assume driving on the right; the angle comes from the navigation source. These previews show appearance, not automatic page switching.</p>
    <div className="nav-gif-links"><a href="./media/nav-showcase-stock.gif" target="_blank" rel="noreferrer">Open stock GIF ↗</a><a href="./media/nav-showcase-bitmap.gif" target="_blank" rel="noreferrer">Open bitmap GIF ↗</a></div>
  </div>;
}

export default NavigationShowcase;
