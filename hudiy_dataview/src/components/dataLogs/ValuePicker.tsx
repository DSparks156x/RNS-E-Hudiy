import { TouchTextInput } from '../touchKeyboard/TouchTextInput';
import { useMemo, useState } from 'react';
import { catalogMatches, CatalogValue, groupOrder, systemName, systemOrder, unitText, valueGroup } from './model';
import { Icon } from './Icons';

export function ValuePicker({ catalog, selected, single = false, minSelected = 0, title, onCancel, onDone }: {
  catalog: CatalogValue[]; selected: string[]; single?: boolean; minSelected?: number; title: string;
  onCancel: () => void; onDone: (ids: string[]) => void;
}) {
  const [draft, setDraft] = useState(selected);
  const [system, setSystem] = useState('Engine');
  const [group, setGroup] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [chosen, setChosen] = useState(false);
  const searching = !!query.trim();
  const systems = systemOrder.filter(s => catalog.some(v => systemName(v.id) === s));
  const base = useMemo(() => catalog.filter(v => searching ? catalogMatches(v, query) : chosen ? draft.includes(v.id) : system === 'All' || systemName(v.id) === system), [catalog, searching, query, chosen, draft, system]);
  const groups = [...new Set(base.map(valueGroup))].sort((a, b) => groupOrder(a, b, system));
  const showGroups = !searching && !chosen && system !== 'All' && !group;
  const rows = base.filter(v => searching || chosen || !group || valueGroup(v) === group).sort((a, b) => systemName(a.id).localeCompare(systemName(b.id)) || valueGroup(a).localeCompare(valueGroup(b)) || a.id.localeCompare(b.id, undefined, { numeric: true }));
  const heading = searching ? 'Search · all systems' : chosen ? 'Selected values' : group ? `${system} / ${group}` : system === 'All' ? 'All API values' : system;
  let lastSection = '';
  return <div className="dl-picker">
    <div className="dl-toolbar"><button className="dl-button dl-icon" onClick={onCancel} aria-label="Cancel value selection"><Icon name="back" /></button><h2>{title}</h2><TouchTextInput aria-label="Search all API values" placeholder="Search all values" value={query} onValueChange={setQuery} />{!single && <button className="dl-button dl-primary" disabled={draft.length < minSelected} onClick={() => onDone(draft)}>Done · {draft.length}</button>}</div>
    <div className="dl-catalog-layout">
      <aside className="dl-box dl-systems pretty-scroll" aria-label="Value systems">{['All', ...systems].map(s => <button key={s} className={`dl-system ${!searching && !chosen && system === s ? 'active' : ''}`} onClick={() => { setSystem(s); setGroup(null); setChosen(false); setQuery(''); }}><span>{s}</span><small>{s === 'All' ? catalog.length : catalog.filter(v => systemName(v.id) === s).length}</small></button>)}</aside>
      <section className="dl-box dl-catalog-detail"><div className="dl-catalog-context">{group && !searching && !chosen && <button className="dl-button dl-icon" aria-label="Back to value groups" onClick={() => setGroup(null)}><Icon name="back" /></button>}<div className="dl-fill"><strong>{heading}</strong><small>{showGroups ? `${base.length} values · ${groups.length} groups` : `${rows.length} values`}</small></div><button className={`dl-button ${chosen ? 'dl-primary' : ''}`} onClick={() => setChosen(!chosen)}>{chosen ? 'Browse' : `Selected · ${draft.length}`}</button></div>
        {showGroups ? <div className="dl-category-grid pretty-scroll">{groups.map(g => <button className="dl-category" key={g} onClick={() => setGroup(g)}><span><strong>{g}</strong><small>{base.filter(v => valueGroup(v) === g).length} values{base.some(v => valueGroup(v) === g && draft.includes(v.id)) ? ` · ${base.filter(v => valueGroup(v) === g && draft.includes(v.id)).length} selected` : ''}</small></span><Icon name="chevron" size={18} /></button>)}</div> : <div className="dl-catalog-rows pretty-scroll">{rows.length ? rows.map(v => {
          const section = `${systemName(v.id)} / ${valueGroup(v)}`;
          const sectionHeader = (searching || chosen || system === 'All') && section !== lastSection;
          lastSection = section;
          const restricted = v.providers.length > 0 && v.providers.every(p => !p.verified || p.estimated);
          const sources = [...new Set(v.providers.map(p => p.kind === 'diag' ? 'Diagnostic' : p.kind === 'ican' ? 'ICAN' : p.kind))].join(' / ');
          return <div key={v.id}>{sectionHeader && <div className="dl-catalog-section">{section}</div>}<button className={`dl-catalog-row ${draft.includes(v.id) ? 'selected' : ''}`} title={v.note || v.id} onClick={() => single ? onDone([v.id]) : setDraft(prev => prev.includes(v.id) ? prev.filter(id => id !== v.id) : [...prev, v.id])}>{!single && <span className="dl-check">{draft.includes(v.id) && <Icon name="check" size={16} />}</span>}<span><strong>{v.label}</strong><small>{unitText(v.unit) || (v.unit_policy === 'reported' ? 'ECU unit' : 'Unitless')} · {sources}{v.type !== 'number' && ` · ${v.type}`}{restricted && ' · Provider opt-in required'}</small></span></button></div>;
        }) : <div className="dl-empty">{chosen ? 'No values selected' : 'No matching values'}</div>}</div>}
      </section>
    </div>
  </div>;
}
