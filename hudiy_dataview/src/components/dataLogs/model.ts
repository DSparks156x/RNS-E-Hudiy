import { disIconTerms } from './disPixelAssets';

export type ValueRequest = string | { id: string; allow_estimated?: boolean; allow_unverified?: boolean; source?: string; rate_hz?: number; period_ms?: number };
export interface CatalogValue {
  id: string; label: string; unit: string | null; type: string; note?: string; unit_policy?: string;
  providers: Array<{ kind: string; verified: boolean; estimated: boolean }>;
}
export interface LogProfile { id: string; name: string; values: ValueRequest[]; allow_estimated?: boolean; allow_unverified?: boolean }
export interface DISSlot { value_id: string; icon: string; unit: string | null; precision: number; font: 'fixed' | 'proportional'; allow_estimated?: boolean; allow_unverified?: boolean }
export interface DISPage { id: string; name: string; profile_id: string; slots: DISSlot[] }
export interface LogConfig { version: number; profiles: LogProfile[]; dis_pages: DISPage[]; settings: Record<string, unknown> }
export interface Session { id: string; name?: string; profile_id: string; started_at: number; duration_sec: number; values: ValueRequest[]; requests?: ValueRequest[]; catalog?: CatalogValue[]; sample_count?: number; recording?: boolean }
export interface Recording { recording: boolean; session_id?: string; profile_id?: string; elapsed_sec: number; samples: number; markers: number; dropped_rows?: number; last_error?: string }
export interface LogState extends LogConfig { catalog: CatalogValue[]; sessions: Session[]; recording: Recording }
export interface LogSample { id: string; value: number | string | null; unit: string | null; status: string; timestamp: number | null; event_at: number; received_at?: number; sample_sequence?: number; quality?: { estimated?: boolean; verified?: boolean } }
export interface LogMarker { timestamp: number; note?: string; label?: string }
export interface LogReview { session: Session; samples: LogSample[]; markers: LogMarker[]; truncated?: boolean }
export const valueId = (value: ValueRequest) => typeof value === 'string' ? value : value.id;
export const profileRequests = (profile?: LogProfile): ValueRequest[] => (profile?.values || []).map(value => ({ ...(profile?.allow_estimated ? { allow_estimated: true } : {}), ...(profile?.allow_unverified ? { allow_unverified: true } : {}), ...(typeof value === 'string' ? { id: value } : value) }));
export const catalogMatches = (value: CatalogValue, query: string) => `${value.label} ${value.id} ${systemName(value.id)} ${valueGroup(value)}`.toLowerCase().includes(query.trim().toLowerCase());
export const systemName = (id: string) => ({ engine: 'Engine', transmission: 'Transmission', awd: 'AWD', vehicle: 'Vehicle / body', climate: 'Climate', ambient: 'Ambient', parking: 'Parking' }[id.split('.')[0]] || 'Other');
export const systemOrder = ['Engine', 'Transmission', 'AWD', 'Vehicle / body', 'Climate', 'Ambient', 'Parking', 'Other'];
export function valueGroup({ id }: Pick<CatalogValue, 'id'>): string {
  const ns = id.split('.')[0];
  if (ns === 'engine') {
    const groups: Array<[RegExp, string]> = [
      [/misfire/, 'Misfires'], [/temperature|coolant|cooling|radiator|thermostat|overheat/, 'Temperatures & cooling'],
      [/lambda|catalyst/, 'Lambda & catalyst'], [/ignition_timing|timing_retard|knock/, 'Ignition & knock'],
      [/camshaft|cam\./, 'Cam timing'], [/fuel|inject|overrun/, 'Fuel & injection'],
      [/boost|maf|load\.|atmospheric|n75|altitude|vacuum|runner_flap/, 'Air & boost'],
      [/throttle|pedal/, 'Throttle & pedal'], [/rpm|idle|time_since_start/, 'Engine speed & idle'],
      [/cruise|speed_limiter|brake|clutch_switch/, 'Cruise & switches'],
      [/voltage|terminal|generator|glow|starter|start_interlock|start_stop|recuperation|preglow/, 'Electrical & starting'],
      [/evap|secondary_air|exhaust|egr|obd/, 'Emissions & OBD'], [/identification|module_communication|vehicle_mileage/, 'Identification & modules'],
    ];
    return groups.find(([pattern]) => pattern.test(id))?.[1] || 'Status & adaptation';
  }
  if (ns === 'transmission') return /clutch[12]/.test(id) ? 'Clutches' : /selector.*travel/.test(id) ? 'Selector travel' : /temperature/.test(id) ? 'Temperatures' : 'Selector & shift state';
  if (ns === 'awd') return /temperature/.test(id) ? 'Temperatures' : /oil_pressure|valve|supply_voltage/.test(id) ? 'Pressure, valve & supply' : /yaw|acceleration|curvature/.test(id) ? 'Yaw & dynamics' : /energy|slip|hold_timer|gear_factor/.test(id) ? 'Slip & energy' : /torque|reference|proactive|ceiling/.test(id) ? 'Torque & control' : 'Inputs & operating state';
  if (ns === 'vehicle') {
    const groups: Array<[RegExp, string]> = [[/steering|yaw/, 'Steering & yaw'], [/abs|esp|brak|stabilization|rough_road|handbrake/, 'Brakes & stability'], [/speed_from|wheel\.|axle|tyre|path_puls|substitute_speed|^vehicle.speed$/, 'Speed & wheels'], [/fuel|range|odometer|trip\.|driving|parked_duration/, 'Fuel, range & trip'], [/battery|generator|energy|electrical|consumer|voltage|shutdown|recuperation|charging/, 'Electrical & energy'], [/key_|ignition|terminal|starter|emergency_start/, 'Ignition & terminals'], [/door|hood|tailgate|light|beam|brightness|signal|fog|window_heating/, 'Doors & lighting']];
    return groups.find(([pattern]) => pattern.test(id))?.[1] || 'Drive & body status';
  }
  if (ns === 'climate') return /temperature|pressure|torque|duty|solar/.test(id) ? 'Measurements' : 'Controls & state';
  if (ns === 'ambient') return /fault/.test(id) ? 'Sensor state' : 'Temperatures';
  if (ns === 'parking') return /distance/.test(id) ? 'Distances' : 'Operating state';
  return 'Other';
}
const engineGroups = ['Air & boost', 'Temperatures & cooling', 'Fuel & injection', 'Ignition & knock', 'Lambda & catalyst', 'Misfires', 'Cam timing', 'Throttle & pedal', 'Engine speed & idle', 'Electrical & starting', 'Cruise & switches', 'Emissions & OBD', 'Status & adaptation', 'Identification & modules'];
export function groupOrder(a: string, b: string, system: string) {
  const order = system === 'Engine' ? engineGroups : [];
  return (order.includes(a) ? order.indexOf(a) : order.length) - (order.includes(b) ? order.indexOf(b) : order.length) || a.localeCompare(b);
}
export const unitText = (unit: string | null | undefined) => unit === 'C' ? '°C' : unit === 'F' ? '°F' : unit === 'deg' ? '°' : unit || '';
export const clock = (sec: number) => `${Math.floor(Math.max(0, sec) / 60).toString().padStart(2, '0')}:${Math.floor(Math.max(0, sec) % 60).toString().padStart(2, '0')}`;
export const iconFor = (id: string) => disIconTerms.find(([term]) => id.toLowerCase().includes(term))?.[1] || 'engine';
export function unitOptions(unit: string | null) {
  if (['C', '°C', 'F', '°F'].includes(unit || '')) return ['C', 'F'];
  if (['bar', 'mbar', 'kPa', 'psi'].includes(unit || '')) return ['mbar', 'bar', 'kPa', 'psi'];
  if (['km/h', 'mph'].includes(unit || '')) return ['km/h', 'mph'];
  return [unit || ''];
}
