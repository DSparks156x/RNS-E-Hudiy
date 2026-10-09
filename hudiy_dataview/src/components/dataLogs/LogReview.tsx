import { TouchTextInput } from '../touchKeyboard/TouchTextInput';
import { useMemo, useState } from 'react';
import { CatalogValue, clock, LogReview as ReviewData, LogSample, unitText, valueId } from './model';
import { Icon } from './Icons';
import { ValuePicker } from './ValuePicker';
import { eventTime, tracePath, validNumber } from './reviewMath';

const colors = ['var(--primary)', '#ffcd2e', '#55bbff', '#7bd59b', '#d19aff', '#ff9b6b'];
export function LogReview({ data, catalog, onRange }: { data: ReviewData; catalog: CatalogValue[]; onRange: (range: { window_sec?: number; since?: number; until?: number }) => Promise<void> }) {
  const recordedIds = [...new Set([...data.session.values.map(valueId), ...data.samples.map(s => s.id)])];
  const numericCatalog = catalog.filter(v => recordedIds.includes(v.id) && v.type === 'number');
  const [traces, setTraces] = useState(() => numericCatalog.slice(0, 3).map(v => v.id));
  const [picker, setPicker] = useState(false);
  const [events, setEvents] = useState(false);
  const start = data.session.started_at;
  const duration = Math.max(data.session.duration_sec || 0, 1);
  const [windowRange, setWindowRange] = useState<[number, number]>([Math.max(0, duration - 30), duration]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [eventQuery, setEventQuery] = useState('');
  const samples = useMemo(() => {
    const result = new Map<string, LogSample[]>();
    for (const sample of data.samples) { const existing = result.get(sample.id) || []; existing.push(sample); result.set(sample.id, existing); }
    for (const entries of result.values()) entries.sort((a, b) => eventTime(a) - eventTime(b));
    return result;
  }, [data.samples]);
  // Group by units reported in each sample, so an ECU unit change never joins incompatible traces.
  const unitGroups = useMemo(() => {
    const result = new Map<string, string[]>();
    for (const id of traces) {
      const units = [...new Set((samples.get(id) || []).filter(validNumber).map(s => s.unit || ''))];
      for (const unit of units) result.set(unit, [...(result.get(unit) || []), id]);
    }
    return [...result.entries()];
  }, [traces, samples]);
  const span = windowRange[1] - windowRange[0];
  const zoom = (factor: number) => {
    const center = cursor !== null && cursor >= windowRange[0] && cursor <= windowRange[1] ? cursor : (windowRange[0] + windowRange[1]) / 2;
    const nextSpan = Math.min(duration, Math.max(.25, span * factor));
    const left = Math.max(0, Math.min(duration - nextSpan, center - nextSpan / 2));
    setWindowRange([left, left + nextSpan]); void onRange({ since: start + left, until: start + left + nextSpan });
  };
  const pan = (direction: number) => { const left = Math.max(0, Math.min(duration - span, windowRange[0] + direction * span / 2)); setWindowRange([left, left + span]); void onRange({ since: start + left, until: start + left + span }); };
  const nearest = (id: string) => {
    const entries = samples.get(id) || [];
    const target = start + (cursor ?? windowRange[1]);
    // Inspect the last acquired sample at or before the cursor, including non-ok samples.
    let found: LogSample | undefined;
    for (const sample of entries) { if (eventTime(sample) > target) break; found = sample; }
    return found;
  };
  const statusSamples = data.samples.filter(s => catalog.find(v => v.id === s.id)?.type !== 'number' || s.status !== 'ok').filter(s => `${s.id} ${s.value} ${s.status}`.toLowerCase().includes(eventQuery.toLowerCase()));
  if (picker) return <ValuePicker title="Choose graph traces" catalog={numericCatalog} selected={traces} onCancel={() => setPicker(false)} onDone={ids => { setTraces(ids); setPicker(false); }} />;
  return <div className="dl-review">
    <div className="dl-review-toolbar"><button className={`dl-button ${!events ? 'dl-primary' : ''}`} onClick={() => setEvents(false)}><Icon name="chart" />Graphs</button><button className={`dl-button ${events ? 'dl-primary' : ''}`} onClick={() => setEvents(true)}>Events · {statusSamples.length}</button><div className="dl-fill dl-caption">{clock(windowRange[0])}–{clock(windowRange[1])} / {clock(duration)}</div>{events ? <TouchTextInput aria-label="Search recorded events" placeholder="Search events" value={eventQuery} onValueChange={setEventQuery} /> : <><button className="dl-button" onClick={() => setPicker(true)}>Traces · {traces.length}</button><button className="dl-button dl-icon" aria-label="Zoom in" onClick={() => zoom(.5)}>+</button><button className="dl-button dl-icon" aria-label="Zoom out" onClick={() => zoom(2)}>−</button></>}</div>
    {events ? <div className="dl-box dl-event-list pretty-scroll">{statusSamples.length ? statusSamples.slice(-500).map((sample, index) => <div className="dl-event" key={`${sample.id}:${sample.timestamp}:${index}`}><time>{clock(eventTime(sample) - start)}</time><span className="dl-fill"><strong>{catalog.find(v => v.id === sample.id)?.label || sample.id}</strong><small>{sample.status}{sample.quality?.estimated ? ' · estimated' : ''}</small></span><code>{sample.status === 'ok' && sample.value !== null ? String(sample.value) : '—'} {unitText(sample.unit)}</code></div>) : <div className="dl-empty">No recorded events match</div>}</div> : <div className="dl-review-body"><div className="dl-plots pretty-scroll">{unitGroups.length ? unitGroups.map(([unit, ids]) => {
      const visible = ids.flatMap(id => (samples.get(id) || []).filter(s => validNumber(s) && (s.unit || '') === unit && eventTime(s) - start >= windowRange[0] && eventTime(s) - start <= windowRange[1]));
      const values = visible.map(s => s.value as number);
      const min = values.length ? values.reduce((a, b) => Math.min(a, b), Infinity) : 0;
      const max = values.length ? values.reduce((a, b) => Math.max(a, b), -Infinity) : 1;
      const padding = Math.max((max - min) * .08, .01);
      const yMin = min - padding, yMax = max + padding;
      const x = (timestamp: number) => 45 + ((timestamp - start - windowRange[0]) / span) * 505;
      const y = (value: number) => 85 - ((value - yMin) / (yMax - yMin)) * 72;
      return <div className="dl-box dl-plot" key={unit}><div className="dl-plot-label">{unitText(unit) || 'Unitless'}</div><svg viewBox="0 0 565 105" role="img" aria-label={`Recorded ${unitText(unit) || 'unitless'} traces. Tap to inspect.`} onPointerDown={e => { e.stopPropagation(); const box = e.currentTarget.getBoundingClientRect(); setCursor(windowRange[0] + Math.max(0, Math.min(1, ((e.clientX - box.left) / box.width * 565 - 45) / 505)) * span); }} onPointerUp={e => e.stopPropagation()}>
        {[0, .5, 1].map(fraction => <g key={fraction}><path d={`M45 ${13 + fraction * 72}H550`} stroke="var(--outline-variant)" /><text x="40" y={16 + fraction * 72} textAnchor="end">{(yMax - fraction * (yMax - yMin)).toFixed(1)}</text></g>)}
        <text x="45" y="102">{clock(windowRange[0])}</text><text x="550" y="102" textAnchor="end">{clock(windowRange[1])}</text>
        {ids.map(id => {
          const entries = samples.get(id) || [];
          const path = tracePath(entries, unit, start + windowRange[0], start + windowRange[1], x, y);
          return <path key={id} d={path} fill="none" stroke={colors[traces.indexOf(id) % colors.length]} strokeWidth="2" />;
        })}
        {data.markers.filter(m => m.timestamp - start >= windowRange[0] && m.timestamp - start <= windowRange[1]).map((marker, i) => <path key={i} d={`M${x(marker.timestamp)} 10V88`} stroke="var(--on-surface-variant)" strokeDasharray="3 3"><title>{marker.note || marker.label || 'Marker'}</title></path>)}
        {cursor !== null && cursor >= windowRange[0] && cursor <= windowRange[1] && <path d={`M${x(start + cursor)} 10V88`} stroke="var(--on-surface)" />}
      </svg></div>;
    }) : <div className="dl-box dl-empty">{traces.length ? 'No valid numeric samples in this recording' : 'Choose traces to graph'}</div>}</div><aside className="dl-box dl-trace-list pretty-scroll"><div className="dl-catalog-section">{cursor === null ? 'Last sample' : `Inspect · ${clock(cursor)}`}</div>{traces.map((id, index) => {
      const sample = nearest(id);
      return <div className="dl-trace" key={id}><span className="dl-trace-dot" style={{ background: colors[index % colors.length] }} /><span className="dl-fill"><strong>{catalog.find(v => v.id === id)?.label || id}</strong><small>{sample?.status || 'No sample'}</small></span><code>{sample && validNumber(sample) ? (sample.value as number).toFixed(2) : '—'}<small>{unitText(sample?.unit)}</small></code></div>;
    })}{data.markers.map((marker, i) => <button className="dl-marker-jump" key={i} onClick={() => { const point = Math.max(0, Math.min(duration, marker.timestamp - start)); setCursor(point); const left = Math.max(0, Math.min(duration - span, point - span / 2)); setWindowRange([left, left + span]); void onRange({ since: start + left, until: start + left + span }); }}><Icon name="marker" size={16} /><span>{clock(marker.timestamp - start)} · {marker.note || marker.label || 'Marker'}</span></button>)}</aside></div>}
    {data.truncated && <small className="dl-caption">Review sample limit reached. Narrow the time window; CSV includes the full recording.</small>}{events && statusSamples.length > 500 && <small className="dl-caption">Showing the latest 500 matching events in this window</small>}{!events && <div className="dl-review-nav"><button className="dl-button" onClick={() => pan(-1)} disabled={windowRange[0] <= 0}>‹ Earlier</button>{[10, 30].map(seconds => <button className="dl-button" key={seconds} onClick={() => { setWindowRange([Math.max(0, duration - seconds), duration]); setCursor(null); void onRange({ window_sec: seconds }); }}>Last {seconds}s</button>)}<button className="dl-button" onClick={() => { setWindowRange([0, duration]); setCursor(null); void onRange({}); }}>Full log</button><button className="dl-button" onClick={() => pan(1)} disabled={windowRange[1] >= duration}>Later ›</button></div>}
  </div>;
}
