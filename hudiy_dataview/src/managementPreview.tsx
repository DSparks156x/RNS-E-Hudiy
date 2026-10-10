/** Explicit developer-only fixture. Production management.tsx never imports it. */
import { createRoot } from 'react-dom/client';
import { ManagementApp, ManagementApi } from './ManagementApp';
import { ConfigDocument, ManagedService, Metadata } from './managementModel';
import { VIDEO_DEFAULTS, VideoSnapshot } from './videoModel';
import { RnseControlSnapshot } from './rnseBridgeModel';
import { ADC_REG_DEFAULTS, AdcPreset, AdcSnapshot } from './rnseAdcModel';
const theme = { primary: '#c4d1b4', onPrimary: '#26331c', primaryContainer: '#3c4b30', onPrimaryContainer: '#e0edce', background: '#11140f', surface: '#1a1e17', onSurface: '#e2e3d9', onSurfaceVariant: '#c5c8bd', outline: '#8d9385', outlineVariant: '#41483b', error: '#ffb4ab', errorContainer: '#93000a', darkThemeEnabled: true };
let document: ConfigDocument = { rnse: { auto_brightness: { enabled: true, day_brightness: 10, night_brightness: 5 }, auto_lcd_brightness: { enabled: true, day_brightness: 100, night_brightness: 6 }, manual_brightness: 10, manual_lcd_brightness: 0, source_label: { enabled: true } }, display: { center_display: { enabled: true, mode: 'nav', high_resolution: true, navigation: { auto_switch: true, auto_switch_approach_threshold: 500 } } }, branch: 'testing', repo: 'https://github.com/DSparks156x/RNS-E-Hudiy', future_setting: ['preserved', null] };
let revision = 'preview-1';
// This fixture never controls a compositor. Production does not import it.
const video: VideoSnapshot = { available: true, status: 'sample', outputs: [{ output: 'HDMI-A-1', name: 'HDMI-A-1', description: 'Sample RNS-E display' }], gamma_protocol: true, active: false, output: 'HDMI-A-1', settings: { ...VIDEO_DEFAULTS }, saved_profile: null, profile_path: '/home/pi/.hudiy/share/video-color.json' };
// Also a fixture: these values never send CAN frames.
const bridge: RnseControlSnapshot = { state: 'ready', mode: 'day', level: 10, lcd_brightness: 100, effective_lcd_brightness: 100, source: 2, manual_overrides: { brightness: null, lcd_brightness: null }, queued: false, protocol_available: true, radio_active: true, source_evidence: 'reported_provider' };
let metadata: Metadata = {};
const adc: AdcSnapshot = { reply_id: 0x462, reply_configured: true, state: 'sample', inhibited: false, radio_active: true, clamp_duration_default: 47,
  registers: [...Array.from({length:30}, (_, i) => i), 0x24, 0x31, 0x35, 0x36, 0x37, 0x41, 0x43, 0x45, 0x46].map(register => { const key = register.toString(16).padStart(2,'0').toUpperCase(); const value = ADC_REG_DEFAULTS[key] ?? (key === '15' ? 2 : key === '11' ? 32 : 0); return { register: key, value, baseline: value, changed: false, failed: false }; }), writes: {}, dump: { state: 'complete', received_sequences: [0,1,2,3,4,5,6,7] } };
const adcPresets: Record<string, AdcPreset> = {};
try { metadata = await (await fetch('/static/configMetadata.json')).json(); } catch { metadata = { sections: [{ id: 'rnse', root: 'rnse', title: 'RNS-E' }, { id: 'display', root: 'display', title: 'Cluster display' }] }; }
const services: ManagedService[] = [
  { id: 'dis_display', label: 'Center DIS', unit: 'dis_display.service', active_state: 'active', sub_state: 'running', description: 'Navigation, music, calls and custom reading pages.', can_control: true },
  { id: 'can_keyboard_control', label: 'RNS-E & wheel controls', unit: 'can_keyboard_control.service', active_state: 'active', sub_state: 'running', description: 'Button mappings and shared steering-wheel controls.', can_control: true },
  { id: 'hudiy_dataview', label: 'Hudiy DataView', unit: 'hudiy_dataview.service', active_state: 'active', sub_state: 'running', description: 'Readings, diagnostics, data logs and the file portal.', can_control: true },
];
const api: ManagementApi = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  let result: unknown;
  if (path === '/metadata') result = metadata;
  else if (path === '/test-pattern/open') throw new Error('Sample preview uses browser fullscreen; no native viewer is launched.');
  else if (path === '/rnse-adc') result = adc;
  else if (path === '/rnse-adc/identify') {
    adc.identification = {
      state: 'identified', chip: 'AD9985', restore_confirmed: true, error: null,
      probe: { requested: 4, readback: 4, status: 0, state: 'ok' },
      restore: { requested: 0, readback: 0, status: 0, state: 'ok' },
    };
    result = adc;
  }
  else if (path === '/rnse-adc/presets') {
    if (init?.method === 'POST') { const body = JSON.parse(String(init.body)); adcPresets[body.name] = body.values; }
    result = { presets: adcPresets };
  }
  else if (path === '/rnse-adc/dump') { adc.dump = { state: 'complete', received_sequences: [0,1,2,3,4,5,6,7] }; result = adc; }
  else if (path === '/rnse-adc/write' || path === '/rnse-adc/revert') {
    const values: AdcPreset = path.endsWith('/revert') ? Object.fromEntries(Object.entries(ADC_REG_DEFAULTS).filter(([key]) => key !== '24')) : JSON.parse(String(init?.body)).values;
    for (const [register, value] of Object.entries(values)) { const row = adc.registers?.find(item => item.register === register); if (row) { row.value = value; row.changed = row.baseline !== value; } adc.writes![register] = { requested: value, readback: value, status: 0, state: 'ok' }; }
    result = adc;
  }
  else if (path === '/rnse-control') result = bridge;
  else if (path === '/rnse-control/manual') {
    const body = JSON.parse(String(init?.body));
    if ('brightness' in body) { bridge.level = body.brightness; bridge.manual_overrides.brightness = body.brightness; }
    if ('lcd_brightness' in body) { bridge.lcd_brightness = body.lcd_brightness; bridge.effective_lcd_brightness = body.lcd_brightness === 0 ? 0 : Math.max(6, body.lcd_brightness); bridge.manual_overrides.lcd_brightness = body.lcd_brightness; }
    bridge.queued = true;
    result = bridge;
  }
  else if (path === '/rnse-control/reload') {
    const settings = document.rnse as { auto_brightness: { enabled: boolean; day_brightness: number }; auto_lcd_brightness: { enabled: boolean; day_brightness: number }; manual_brightness: number; manual_lcd_brightness: number };
    bridge.level = settings.auto_brightness.enabled ? settings.auto_brightness.day_brightness : settings.manual_brightness;
    bridge.lcd_brightness = settings.auto_lcd_brightness.enabled ? settings.auto_lcd_brightness.day_brightness : settings.manual_lcd_brightness;
    bridge.effective_lcd_brightness = bridge.lcd_brightness === 0 ? 0 : Math.max(6, bridge.lcd_brightness);
    bridge.manual_overrides = { brightness: null, lcd_brightness: null }; bridge.queued = true; result = bridge;
  }
  else if (path === '/video') result = video;
  else if (path === '/video/apply') { const body = JSON.parse(String(init?.body)); await new Promise(resolve => setTimeout(resolve, 100)); video.active = true; video.settings = body.settings; video.output = body.output || 'HDMI-A-1'; result = video; }
  else if (path === '/video/profile') { const body = JSON.parse(String(init?.body)); video.saved_profile = { output: body.output, settings: body.settings }; result = video; }
  else if (path === '/video/reset') { video.active = false; video.settings = { ...VIDEO_DEFAULTS }; video.saved_profile = null; result = video; }
  else if (path === '/theme') result = { theme };
  else if (path === '/configs') result = { pin_required: false, configs: [{ id: 'rnse', label: 'RNSE config.json · sample', filename: '/home/pi/config.json', exists: true }] };
  else if (path === '/configs/rnse') {
    if (init?.method === 'PUT') { const body = JSON.parse(String(init.body)); document = body.document; revision = `preview-${Number(revision.split('-')[1]) + 1}`; }
    result = { id: 'rnse', label: 'RNSE configuration', filename: '/home/pi/config.json', document, revision, backup: init ? '/home/pi/confbackup/preview/config.json' : undefined, affected_services: ['dis_display', 'can_keyboard_control'] };
  } else if (path === '/services') result = { services };
  else if (path.includes('/logs?')) result = { text: '[sample log · no vehicle connection]\n10:42:01 INFO Center DIS ready\n10:42:02 INFO Shared readings: 6 requested, 6 available\n10:42:05 INFO Navigation approach: 500 m\n10:42:06 DEBUG Rendering bitmap maneuver: turn_left' };
  else if (/^\/services\/[^/]+\/(start|stop|restart)$/.test(path)) { const [, , id, action] = path.split('/'); const service = services.find(item => item.id === id); if (service) { service.active_state = action === 'stop' ? 'inactive' : 'active'; service.sub_state = action === 'stop' ? 'dead' : 'running'; } result = { message: `${action} simulated for ${id}.` }; }
  else throw new Error('Unsupported sample preview request.');
  return JSON.parse(JSON.stringify(result)) as T;
};
const root = window.document.getElementById('root');
if (!root) throw new Error('No root element.');
// Simulate the native color bridge so the fixture exercises the head-unit keyboard.
window.hudiy = { colorScheme: theme };
createRoot(root).render(<ManagementApp api={api} previewTheme={theme} />);
