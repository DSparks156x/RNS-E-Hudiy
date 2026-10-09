import catalog from './capture-value-catalog.json';
export { catalog };
const profileValues = ['engine.boost.actual_absolute', 'engine.boost.spec_absolute', 'engine.rpm', 'engine.maf', 'engine.intake_temperature', 'engine.timing_retard.cylinder2'];
const start = 1791468000;
const session = { id: 'sample-boost-log', name: 'Boost & timing', profile_id: 'boost-timing', started_at: start, duration_sec: 30, values: profileValues, catalog, sample_count: 606, recording: false };
const profiles = [{ id: 'boost-timing', name: 'Boost & timing', values: profileValues }, { id: 'temperatures', name: 'Temperatures', values: ['engine.oil_temperature', 'engine.coolant_temperature', 'engine.intake_temperature', 'transmission.fluid_temperature'] }];
const slotValues = ['engine.rpm', 'engine.boost.actual_absolute', 'engine.oil_temperature', 'engine.coolant_temperature', 'engine.intake_temperature', 'engine.maf', 'transmission.fluid_temperature', 'vehicle.speed'];
const state = { version: 1, catalog, profiles, settings: {}, dis_pages: [{ id: 'drive', name: 'Drive', profile_id: 'boost-timing', slots: slotValues.map(id => ({ value_id: id, icon: 'auto', unit: id === 'engine.boost.actual_absolute' ? 'bar' : null, precision: id === 'engine.boost.actual_absolute' ? 2 : 0, font: 'fixed' })) }], sessions: [session], recording: { recording: false, elapsed_sec: 0, samples: 0, markers: 0, dropped_rows: 0 } };
const samples = Array.from({ length: 101 }, (_, i) => profileValues.map(id => {
  const t = i * .3, pull = Math.sin(Math.PI * t / 30) ** 2;
  const value = { 'engine.boost.actual_absolute': 1000 + 980 * pull - 60 * Math.sin(t * .9), 'engine.boost.spec_absolute': 1000 + 1030 * pull, 'engine.rpm': 1500 + 3800 * pull, 'engine.maf': 22 + 150 * pull, 'engine.intake_temperature': 32 + 8 * pull, 'engine.timing_retard.cylinder2': t > 12 && t < 20 ? 1.5 : 0 }[id];
  return { id, value, unit: catalog.find(v => v.id === id).unit, status: 'ok', timestamp: start + t, event_at: start + t, sample_sequence: i + 1, quality: { verified: true, estimated: false } };
})).flat();
const markers = [{ timestamp: start + 8.4, note: 'Driver marker' }, { timestamp: start + 20.1, note: 'Driver marker' }];

// All Data & Logs fetches are handled in-memory. Reject unknown requests instead
// of falling through to a real backend. Config changes last only until reload.
export function installDataLogsFixture() {
  window.fetch = async (resource, init = {}) => {
    const url = new URL(typeof resource === 'string' ? resource : resource.url, window.location.href);
    if (!url.pathname.startsWith('/api/data-logs')) throw new Error(`Capture fixture blocked ${url.pathname}`);
    const path = url.pathname.slice('/api/data-logs'.length);
    const body = init.body ? JSON.parse(init.body) : {};
    if (path === '/config' && init.method === 'PUT') Object.assign(state, body);
    if (path === '/start') state.recording = { recording: true, session_id: session.id, profile_id: body.profile_id, elapsed_sec: 18, samples: 360, markers: 2, dropped_rows: 0 };
    if (path === '/stop') state.recording = { recording: false, elapsed_sec: 0, samples: 0, markers: 0, dropped_rows: 0 };
    if (path === '/marker') state.recording.markers++;
    let response = path === '/status' ? state.recording : state;
    if (path.startsWith('/sessions/')) {
      const since = Number(url.searchParams.get('since') || start);
      const until = Number(url.searchParams.get('until') || start + 30);
      response = { session, samples: samples.filter(s => s.event_at >= since && s.event_at <= until), markers };
    }
    return new Response(JSON.stringify(response), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
}
