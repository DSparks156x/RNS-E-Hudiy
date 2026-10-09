import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { defaults, ConfigSourceContext } from './ui';
import { topics, groups, Pages } from './guide';
import './style.css';

const aliases = { dis: 'navigation', config: 'configuration' };
function currentTopic() {
  const requested = location.hash.slice(1);
  const id = aliases[requested] || requested;
  return topics.some(topic => topic.id === id) ? id : 'overview';
}
function App() {
  const [topic, setTopic] = useState(currentTopic);
  const [query, setQuery] = useState('');
  const [menu, setMenu] = useState(false);
  const [selection, setSelection] = useState(defaults);
  useEffect(() => {
    const handler = () => { setTopic(currentTopic()); setMenu(false); setQuery(''); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  useEffect(() => { document.title = `${topics.find(t => t.id === topic)?.title} · RNS-E Hudiy`; }, [topic]);
  const selected = topics.find(t => t.id === topic);
  const results = topics.filter(t => `${t.title} ${t.summary} ${t.keywords}`.toLowerCase().includes(query.toLowerCase()));
  const Page = Pages[topic];
  return <>
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content').focus(); }}>Skip to content</a>
    <div className="mobile-bar"><a href="#overview">RNS-E <strong>Hudiy</strong></a><button aria-expanded={menu} aria-controls="navigation" aria-label="Toggle navigation" onClick={() => setMenu(!menu)}>☰</button></div>
    <aside id="navigation" className={`sidebar ${menu ? 'open' : ''}`}>
      <a className="brand" href="#overview"><span className="brand-mark">▣</span><span>RNS-E <b>Hudiy</b><small>FEATURES & SETUP</small></span></a>
      <label className="search-label"><span className="sr-only">Find a feature or task</span><span aria-hidden="true">⌕</span><input placeholder="Find a feature or task" value={query} onChange={e => setQuery(e.target.value)}/></label>
      <nav aria-label="Guide topics">
        {groups.map(group => {
          const entries = results.filter(t => t.group === group.id);
          return entries.length > 0 && <div className="nav-group" key={group.id}><div className="nav-label">{query ? 'RESULTS / ' : ''}{group.title}</div>{entries.map(t => <a key={t.id} href={`#${t.id}`} aria-current={topic === t.id ? 'page' : undefined} className={topic === t.id ? 'active' : ''}><span aria-hidden="true" className="icon">{t.icon}</span>{t.title}{topic === t.id && <span className="nav-dot"/>}</a>)}</div>;
        })}
        {results.length === 0 && <p className="no-results">No match. Try “boost”, “wheel”, “CSV” or “config”.</p>}
      </nav>
      <div className="sidebar-bottom"><a href="https://github.com/DSparks156x/RNS-E-Hudiy" target="_blank" rel="noreferrer">Project on GitHub ↗</a><small>DSparks156x / testing</small></div>
    </aside>
    <main id="main-content" tabIndex="-1">
      <div className="page-top"><span>{topic === 'overview' ? 'PROJECT GUIDE' : <><a href="#overview">Guide</a><span className="breadcrumb-separator">/</span>{selected.title}</>}</span><span className="source-pill">DSparks156x <span>/</span> testing</span></div>
      <ConfigSourceContext.Provider value={selection}><Page selection={selection} setSelection={setSelection}/></ConfigSourceContext.Provider>
      <footer><span>RNS-E Hudiy / Features & setup</span><span>Demos use sample data and actual app renderers.</span><a href="https://github.com/DSparks156x/RNS-E-Hudiy" target="_blank" rel="noreferrer">Source ↗</a></footer>
    </main>
  </>;
}
createRoot(document.getElementById('root')).render(<App/>);
