// In-memory socket replacement, loaded ONLY by capture-vite.config.js.
// Nothing here connects to the vehicle, WebSocket, or Socket.IO backend.
const handlers = new Map();
const haldex = { status: 'synced', desired_mode: 1, desired_name: 'Performance', active_mode: 1, active_name: 'Performance', token_ok: true, b08_torque_nm: 410, a7c_slip_nm: 125, a72_ceiling_nm: 1400, yaw_model_counts: 24, hold_a7e: 0, last_telemetry_age: .08, last_switch_time: 0 };
const logger = { recording: false, profile: 'haldex', available_profiles: [{ name: 'haldex', description: 'Fused Haldex logging' }, { name: 'raw_can', description: 'Raw CAN capture' }], measuring_groups: [], output_path: '', frames_received: 0, rows_written: 0, markers_logged: 0, dropped_rows: 0, uptime_sec: 0, last_error: '', haldex_mode: 1, b08_torque_nm: 410, a7c_slip_torque_nm: 125 };
function receive(name, data) { queueMicrotask(() => [...(handlers.get(name) || [])].forEach(handler => handler(structuredClone(data)))); }
export const fixtureSocket = {
  connected: true,
  on(name, handler) { if (!handlers.has(name)) handlers.set(name, new Set()); handlers.get(name).add(handler); return this; },
  off(name, handler) { handlers.get(name)?.delete(handler); return this; },
  emit(name, data) {
    if (name === 'get_haldex_status') receive('haldex_update', haldex);
    if (name === 'get_logger_status') receive('logger_update', logger);
    if (name === 'set_haldex_mode') { haldex.desired_mode = haldex.active_mode = data.mode; haldex.desired_name = haldex.active_name = ['Stock', 'Performance', 'Competition'][data.mode]; receive('haldex_update', haldex); }
    if (name === 'start_logger') { logger.recording = true; logger.profile = data.profile; receive('logger_update', logger); }
    if (name === 'stop_logger') { logger.recording = false; receive('logger_update', logger); }
    if (name === 'add_logger_marker') { logger.markers_logged++; receive('logger_update', logger); }
    if (name === 'get_tunes_list') receive('tunes_list', [{ name: data?.module === 'pq-eps' ? 'sample-dataset.bin' : 'sample-firmware.bin', artifact_id: 'synthetic-fixture-only', size_bytes: data?.module === 'pq-eps' ? 4096 : 327680, type: 'bin', modified: '2026-10-08' }]);
    if (name === 'get_ecu_flash_info') receive('ecu_flash_info', { connected: true, in_bootloader: false, part_number: 'Sample controller', sw_version: data?.module === 'pq-eps' ? '3001' : '3016', flash_counter: 2, system_desc: 'Synthetic help-site fixture' });
    if (name === 'get_exhaust_valve') { receive('exhaust_valve_status', { target: 100, inhibited: false, update_running: false }); receive('exhaust_valve_artifacts', []); }
    if (name === 'toggle_group' && data.action === 'add' && data.module === 1) {
      // Source-backed block ordering from the production engine catalog:
      // 3 = RPM / MAF / throttle angle / ignition, 20 = per-cylinder retard,
      // 115 = RPM / engine load / specified absolute boost / actual absolute boost.
      const groups = {
        3: [{ value: 3420, unit: 'rpm' }, { value: 128, unit: 'g/s' }, { value: 74, unit: 'deg' }, { value: 14.5, unit: 'deg' }],
        20: [{ value: 0, unit: 'deg' }, { value: 1.5, unit: 'deg' }, { value: 0, unit: 'deg' }, { value: .75, unit: 'deg' }],
        115: [{ value: 3420, unit: 'rpm' }, { value: 78, unit: '%' }, { value: 1980, unit: 'mbar' }, { value: 1850, unit: 'mbar' }],
      };
      if (groups[data.group]) receive('diagnostic_update', { module: 1, group: data.group, data: groups[data.group] });
    }
    if (name === 'request_dtcs') receive('dtc_report', { module: data.module, type: 'dtc_report', dtcs: [] });
    return this;
  },
  disconnect() {},
};
export function io() { queueMicrotask(() => receive('connect', {})); return fixtureSocket; }
