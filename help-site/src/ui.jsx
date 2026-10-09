import React, { createContext, useContext, useState } from 'react';
import './dis-previews.css';

export const defaults = { repo: 'DSparks156x/RNS-E-Hudiy', branch: 'testing' };
export const ConfigSourceContext = createContext(defaults);
export function helperUrl(selection, search = '') {
  const repo = selection.repo.trim().replace(/^https:\/\/github\.com\//, '').replace(/\.git$/, '').replace(/\/$/, '');
  const query = new URLSearchParams({ repo, branch: selection.branch.trim(), load: '1' });
  if (search) query.set('search', search);
  return `./tools/config_editor.html?${query}`;
}
export function SourceLink({ source, children }) {
  return <a className="source-link" href={`https://github.com/DSparks156x/RNS-E-Hudiy/blob/testing/${source}`} target="_blank" rel="noreferrer">{children || 'Source notes'} ↗</a>;
}
export function Note({ children }) { return <aside className="note">{children}</aside>; }
export function DemoImage({ src, alt, pixel = false }) {
  const animated = src.endsWith('.gif');
  const [playing, setPlaying] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const still = { 'dataview-engine.gif': 'dataview-engine.jpg', 'dis-acceleration-run.gif': 'dis-acceleration.png' }[src] || src.replace('.gif', '.png');
  const image = <img src={`./media/${animated && !playing ? still : src}`} alt={alt} loading="lazy" className={pixel ? 'pixel' : ''}/>;
  return <div className={`demo-image${pixel ? ' dis-preview' : ''}`}>{pixel ? <div className="dis-preview-frame">{image}</div> : image}{animated && <button className="demo-toggle" onClick={() => setPlaying(!playing)} aria-label={playing ? 'Pause demonstration' : 'Play demonstration'}>{playing ? 'Ⅱ Pause' : '▷ Play'}</button>}</div>;
}
export function Figure({ src, caption, pixel = false, className = '' }) {
  return <figure className={`${className} ${pixel ? 'pixel-figure' : ''}`}><div className="image-surface"><DemoImage src={src} alt={caption} pixel={pixel}/></div><figcaption>{caption}</figcaption></figure>;
}
export function Steps({ items }) {
  return <ol className="steps">{items.map(([title, text]) => <li key={title}><strong>{title}</strong><p>{text}</p></li>)}</ol>;
}
export function Section({ title, children, id }) {
  return <section className="guide-section" id={id}><h2>{title}</h2>{children}</section>;
}
export function PageHead({ location, title, children }) {
  return <div className="topic-head"><div className="eyebrow">{location}</div><h1>{title}</h1><p className="lead">{children}</p></div>;
}
export function Table({ headings, rows }) {
  return <div className="control-table"><table><thead><tr>{headings.map(heading => <th key={heading}>{heading}</th>)}</tr></thead><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>;
}
export function Settings({ rows }) {
  const selection = useContext(ConfigSourceContext);
  return <Section title="Related settings"><p>These are the settings used by this feature. Select a path to open its full description in the config helper, using <strong>{selection.repo} / {selection.branch}</strong>.</p><Table headings={['Open in config helper ↗', 'Used here for']} rows={rows.map(([path, help]) => [<a href={helperUrl(selection, path)} target="_blank" rel="noreferrer"><code>{path}</code></a>, help])}/><a className="text-button inline-link" href="#configuration">Choose a source or browse the complete config →</a></Section>;
}
export function Related({ links }) {
  return <div className="related"><span className="eyebrow">RELATED</span>{links.map(([id, title, description]) => <a key={id} href={`#${id}`}><span><strong>{title}</strong><small>{description}</small></span><span>→</span></a>)}</div>;
}
export function FeatureDemo({ src, caption, title, children, pixel = true }) {
  return <div className="feature-demo"><Figure src={src} caption={caption} pixel={pixel}/><div><h2>{title}</h2>{children}</div></div>;
}
export function ConfigLaunch({ selection, setSelection }) {
  const [custom, setCustom] = useState(selection.repo !== defaults.repo && selection.repo !== 'Korni92/RNS-E-Hudiy');
  const [error, setError] = useState('');
  const repo = selection.repo.trim().replace(/^https:\/\/github\.com\//, '').replace(/\.git$/, '').replace(/\/$/, '');
  const valid = /^[\w.-]+\/[\w.-]+$/.test(repo) && !!selection.branch.trim();
  function open() {
    if (!valid) { setError('Enter a GitHub repository as owner/repository and a branch.'); return; }
    setError('');
    window.open(helperUrl(selection), '_blank', 'noopener');
  }
  return <div className="config-launch">
    <div className="eyebrow">CONFIGURATION HELPER</div><h2>Open a branch’s config</h2><p>Fetch the latest <code>config.json</code>, edit it in your browser, and download the result.</p>
    <div className="source-fields"><label>Repository<select value={custom ? 'custom' : selection.repo} onChange={e => { const isCustom = e.target.value === 'custom'; setCustom(isCustom); if (!isCustom) setSelection({ ...selection, repo: e.target.value }); }}><option value={defaults.repo}>DSparks156x / RNS-E-Hudiy</option><option value="Korni92/RNS-E-Hudiy">Korni92 / RNS-E-Hudiy</option><option value="custom">Another repository…</option></select></label><label>Branch<input list="branch-options" value={selection.branch} onChange={e => setSelection({ ...selection, branch: e.target.value })}/><datalist id="branch-options"><option value="testing"/><option value="release"/><option value="beta"/><option value="main"/></datalist></label></div>
    {custom && <label className="custom-repo">GitHub owner/repository<input value={selection.repo} onChange={e => setSelection({ ...selection, repo: e.target.value })} placeholder="owner/repository"/></label>}
    <div className="launch-actions"><button className="primary-button" onClick={open}>Open config helper ↗</button>{valid && <a className="text-button" href={`https://github.com/${repo}/tree/${encodeURIComponent(selection.branch.trim())}`} target="_blank" rel="noreferrer">Browse branch ↗</a>}</div>
    {error && <p className="error" role="alert">{error}</p>}
    <p className="fine-print">Defaults to DSparks156x/RNS-E-Hudiy → testing. Selecting another branch changes the config source; this guide describes this fork.</p>
  </div>;
}
