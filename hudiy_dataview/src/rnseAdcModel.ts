// AK5406 map: RNSE hacking/analysis/ak5406_v1/PI_UI_REGISTERS.md. The server re-validates every byte.
export type AdcRegister = string;
export type AdcWriteState = 'queued' | 'queued_unconfirmed' | 'pending' | 'ok' | 'rejected' | 'readback_failed' | 'i2c_error' | 'timeout' | 'queue_failed' | 'not_sent';
export interface AdcRegisterRow { register: string; value: number | null; baseline: number | null; changed?: boolean; failed?: boolean; in_dump?: boolean; access?: 'now' | 'widen' | 'read_only' }
export interface AdcSnapshot {
  reply_id?: number | null; reply_configured?: boolean; inhibited?: boolean; radio_active?: boolean; state?: string;
  command_error?: string | null;
  busy?: boolean;
  registers?: AdcRegisterRow[];
  writes?: Record<string, { requested: number; readback: number | null; status: number | null; state: AdcWriteState }>;
  dump?: { state: string; received_sequences?: number[]; error?: string | null };
  defaults?: Record<string, number>; clock_tuned?: Record<string, number>;
}
export interface AdcPreset { [register: string]: number }
export const ADC_FIRMWARE: AdcPreset = {
  '01': 0x3f, '02': 0x50, '03': 0x30, '04': 0x80, '05': 0x16, '06': 0x2f, '07': 0x70, '08': 0x70, '09': 0x70, '0A': 0x70,
  '0E': 0x2d, '10': 0, '11': 0x20, '12': 6, '13': 6, '17': 1, '18': 0, '19': 1, '1A': 0, '1B': 1, '1C': 0,
  '1D': 0, '1E': 0, '1F': 0, '20': 0, '21': 0, '22': 0, '23': 0, '24': 0x58, '25': 0, '26': 0, '27': 0, '28': 0xf0,
};
const span = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => (from + i).toString(16).padStart(2, '0').toUpperCase());
export const ADC_WRITABLE = new Set([...span(0x01, 0x13).filter(r => !['0B', '0C', '0D', '0F'].includes(r)), ...span(0x17, 0x28)]);
// Stock BC range; everything else in ADC_WRITABLE needs the widening patch.
export const ADC_WRITABLE_NOW = new Set([...ADC_WRITABLE].filter(r => r <= '13' || (r >= '19' && r <= '1B')));
export const CLAMP_LIMIT = 104;

export type AdcPage = 'clock' | 'gain' | 'black' | 'clamp' | 'sync' | 'output';
type Kind = { kind: 'bits'; reg: string; hi: number; lo: number } | { kind: 'enum'; reg: string; bytes: number[] }
  | { kind: 'pll' } | { kind: 'target'; regs: [string, string] } | { kind: 'offset'; regs: [string, string] };
export type AdcField = Kind & { id: string; label: string; page: AdcPage; min: number; max: number; firmware: number; widen?: boolean; advanced?: boolean; detail?: (v: number) => string };
const volts = (v: number) => 1.6 * (128 + v) / 543;
const quarter = (v: number) => `${v / 4 >= 0 ? '+' : ''}${v / 4} codes`;
const pick = <T,>(labels: T[]) => (v: number) => String(labels[v] ?? v);
const gainDetail = (v: number) => `${volts(v).toFixed(3)} V · white ${Math.min(255, Math.round(0.7 / volts(v) * 255))}`;
const bits = (reg: string, hi: number, lo: number) => ({ kind: 'bits' as const, reg, hi, lo });
export const ADC_FIELDS: AdcField[] = [
  { id: 'lineLength', label: 'Line length', page: 'clock', kind: 'pll', min: 224, max: 4096, firmware: 1014, advanced: true, detail: v => `${v} clocks` },
  { id: 'vcoRange', label: 'VCO range (MHz)', page: 'clock', ...bits('03', 7, 6), min: 0, max: 2, firmware: 0, detail: pick(['9–32', '32–64', '64–80']) },
  { id: 'chargePump', label: 'Charge pump', page: 'clock', ...bits('03', 5, 3), min: 0, max: 6, firmware: 6, detail: pick(['50 µA', '100 µA', '150 µA', '250 µA', '350 µA', '500 µA', '750 µA']) },
  { id: 'phase', label: 'Sampling phase', page: 'clock', ...bits('04', 7, 3), min: 0, max: 31, firmware: 16 },
  { id: 'gainR', label: 'Gain · Red', page: 'gain', ...bits('08', 7, 0), min: 0, max: 255, firmware: 0x70, detail: gainDetail },
  { id: 'gainG', label: 'Gain · Green', page: 'gain', ...bits('09', 7, 0), min: 0, max: 255, firmware: 0x70, detail: gainDetail },
  { id: 'gainB', label: 'Gain · Blue', page: 'gain', ...bits('0A', 7, 0), min: 0, max: 255, firmware: 0x70, detail: gainDetail },
  { id: 'loopOff', label: 'Black loop mode', page: 'black', ...bits('23', 2, 2), min: 0, max: 1, firmware: 0, widen: true, detail: pick(['Auto', 'Off (manual)']) },
  { id: 'loopHold', label: 'Black loop hold', page: 'black', ...bits('23', 1, 1), min: 0, max: 1, firmware: 0, widen: true, detail: pick(['Running', 'Frozen']) },
  { id: 'loopUpdate', label: 'Black correction update', page: 'black', ...bits('23', 0, 0), min: 0, max: 1, firmware: 0, widen: true, detail: pick(['Each line', '64 frames']) },
  { id: 'loopCoring', label: 'Black loop coring', page: 'black', ...bits('23', 4, 3), min: 0, max: 3, firmware: 0, widen: true },
  { id: 'loopBandwidth', label: 'Black loop bandwidth', page: 'black', ...bits('23', 7, 5), min: 0, max: 7, firmware: 0, widen: true },
  { id: 'targetR', label: 'Black target · Red', page: 'black', kind: 'target', regs: ['1D', '1E'], min: -16, max: 80, firmware: 0, widen: true, detail: quarter },
  { id: 'targetG', label: 'Black target · Green', page: 'black', kind: 'target', regs: ['1F', '20'], min: -16, max: 80, firmware: 0, widen: true, detail: quarter },
  { id: 'targetB', label: 'Black target · Blue', page: 'black', kind: 'target', regs: ['21', '22'], min: -16, max: 80, firmware: 0, widen: true, detail: quarter },
  { id: 'offsetR', label: 'Manual offset · Red', page: 'black', kind: 'offset', regs: ['17', '18'], min: -256, max: 255, firmware: -1, widen: true, detail: quarter },
  { id: 'offsetG', label: 'Manual offset · Green', page: 'black', kind: 'offset', regs: ['19', '1A'], min: -256, max: 255, firmware: -1, detail: quarter },
  { id: 'offsetB', label: 'Manual offset · Blue', page: 'black', kind: 'offset', regs: ['1B', '1C'], min: -256, max: 255, firmware: -1, widen: true, detail: quarter },
  { id: 'clampStart', label: 'Clamp start', page: 'clamp', ...bits('05', 7, 0), min: 1, max: 255, firmware: 22 },
  { id: 'clampLength', label: 'Clamp length', page: 'clamp', ...bits('06', 7, 0), min: 1, max: 255, firmware: 47 },
  { id: 'clampSlow', label: 'Clamp speed', page: 'clamp', kind: 'enum', reg: '24', bytes: [0x58, 0x78], min: 0, max: 1, firmware: 0, widen: true, detail: pick(['600 µA', '150 µA slow']) },
  { id: 'clampSplit', label: 'Clamp/black-loop split', page: 'clamp', ...bits('25', 7, 0), min: 0, max: 254, firmware: 0, widen: true },
  { id: 'clampCoastPre', label: 'Clamp coast before', page: 'clamp', ...bits('26', 7, 0), min: 0, max: 255, firmware: 0, widen: true },
  { id: 'clampCoastPost', label: 'Clamp coast after', page: 'clamp', ...bits('27', 7, 0), min: 0, max: 255, firmware: 0, widen: true },
  { id: 'syncSource', label: 'Sync source', page: 'sync', kind: 'enum', reg: '0E', bytes: [0x25, 0x2d], min: 0, max: 1, firmware: 1, detail: pick(['HSYNC pin', 'SOG slicer']) },
  { id: 'sogThreshold', label: 'Sync slicer threshold', page: 'sync', ...bits('10', 7, 3), min: 0, max: 31, firmware: 0, detail: v => `${320 - 10 * v} mV` },
  { id: 'syncSeparator', label: 'Sync separator threshold', page: 'sync', ...bits('11', 7, 0), min: 0, max: 255, firmware: 0x20 },
  { id: 'pllCoastPre', label: 'PLL coast before', page: 'sync', ...bits('12', 7, 0), min: 0, max: 255, firmware: 6 },
  { id: 'pllCoastPost', label: 'PLL coast after', page: 'sync', ...bits('13', 7, 0), min: 0, max: 255, firmware: 6 },
  { id: 'hsyncWidth', label: 'HSYNC output width', page: 'output', ...bits('07', 7, 0), min: 1, max: 255, firmware: 112 },
  { id: 'driveData', label: 'Data output drive', page: 'output', ...bits('28', 7, 6), min: 2, max: 3, firmware: 3, widen: true, detail: pick(['', '', '¼', 'Max']) },
  { id: 'driveClock', label: 'Clock output drive', page: 'output', ...bits('28', 5, 4), min: 2, max: 3, firmware: 3, widen: true, detail: pick(['', '', '¼', 'Max']) },
];
export const adcField = (id: string): AdcField => { const field = ADC_FIELDS.find(item => item.id === id); if (!field) throw new RangeError(`Unknown ADC control ${id}.`); return field; };
export const fieldRegisters = (field: AdcField): string[] => field.kind === 'pll' ? ['01', '02'] : field.kind === 'target' || field.kind === 'offset' ? field.regs : [field.reg];
const mask = (hi: number, lo: number) => ((1 << (hi - lo + 1)) - 1) << lo;
// Bits no control owns (03 [2:0], 04 [2:0], 10 [2:0], 28 [3:0]) must stay 0.
const OWNED: Record<string, number> = {};
for (const field of ADC_FIELDS) if (field.kind === 'bits') OWNED[field.reg] = (OWNED[field.reg] ?? 0) | mask(field.hi, field.lo);

/** Bytes to send, in send order (first byte of a pair first). `current` reads a shared register. */
export function encodeAdcField(field: AdcField, value: number, current: (register: string) => number | null = () => null): AdcPreset {
  if (!Number.isInteger(value) || value < field.min || value > field.max) throw new RangeError(`${field.label} must be ${field.min}–${field.max}.`);
  if (field.kind === 'pll') { const div = value - 1; return { '01': div >> 4, '02': (div & 0xf) << 4 }; }
  if (field.kind === 'target') { const v9 = value & 0x1ff; return { [field.regs[0]]: v9 >> 8, [field.regs[1]]: v9 & 0xff }; }
  if (field.kind === 'offset') { const raw = 0xff - value; return { [field.regs[0]]: raw >> 8, [field.regs[1]]: raw & 0xff }; }
  if (field.kind === 'enum') return { [field.reg]: field.bytes[value] };
  const m = mask(field.hi, field.lo), base = (current(field.reg) ?? ADC_FIRMWARE[field.reg]) & OWNED[field.reg];
  return { [field.reg]: (base & ~m) | ((value << field.lo) & m) };
}
/** Null when a byte is unknown or holds a value the control cannot show. */
export function decodeAdcField(field: AdcField, byte: (register: string) => number | null): number | null {
  if (field.kind === 'pll') { const a = byte('01'), b = byte('02'); return a == null || b == null ? null : ((a << 4) | (b >> 4)) + 1; }
  if (field.kind === 'target' || field.kind === 'offset') {
    const a = byte(field.regs[0]), b = byte(field.regs[1]); if (a == null || b == null) return null;
    const v9 = ((a & 1) << 8) | b;
    return field.kind === 'target' ? (v9 & 0x100 ? v9 - 0x200 : v9) : 0xff - v9;
  }
  const value = byte(field.reg); if (value == null) return null;
  if (field.kind === 'enum') { const index = field.bytes.indexOf(value); return index < 0 ? null : index; }
  return (value & mask(field.hi, field.lo)) >> field.lo;
}
export const adcFieldWritableNow = (field: AdcField) => fieldRegisters(field).every(r => ADC_WRITABLE_NOW.has(r));
export const validateClampWindow = (start: number, length: number) => Number.isInteger(start) && Number.isInteger(length) && start >= 1 && length >= 1 && start + length <= CLAMP_LIMIT;
/** Pi pixel clock in MHz for a line length at the 31.52 kHz 480p line rate. */
export const suggestedVcoRange = (lineLength: number) => { const mhz = lineLength * 0.03152; return mhz < 32 ? 0 : mhz < 64 ? 1 : 2; };

// PI_UI_REGISTERS.md presets; Firmware runs the server's fixed Revert.
export const ADC_BUILTIN_PRESETS: Record<string, AdcPreset> = {
  'Banding fix A': { '23': 0x01 },
  'Banding fix B': { '23': 0x01, '24': 0x78 },
  'Banding diagnostic': { '23': 0x02 },
  'TV clamp': { '05': 0x0e, '06': 0x50 },
  'Camera-safe clamp': { '05': 0x0c, '06': 0x39 },
  'Low-noise drive': { '28': 0xb0 },
  'Low PLL bandwidth': { '03': 0x28 },
};

export class ReleasedDraft {
  committed:number; draft:number;
  constructor(value:number){this.committed=this.draft=value;}
  change(value:number){this.draft=value;}
  sync(value:number){this.committed=this.draft=value;}
  cancel(){this.draft=this.committed;return this.committed;}
  release():number|null {if(this.draft===this.committed)return null;this.committed=this.draft;return this.draft;}
}
export function adcWriteMessage(snapshot:AdcSnapshot|null, reg:string):string {
  const write=snapshot?.writes?.[reg]; if(!write) return '';
  if(write.state==='queued') return `Reg ${reg}: waiting to send`;
  if(write.state==='queued_unconfirmed') return `Reg ${reg}: queued, reply unconfirmed`;
  if(write.state==='pending') return `Reg ${reg}: waiting for reply`;
  if(write.state==='ok') return `Reg ${reg}: read back 0x${(write.readback ?? 0).toString(16).padStart(2,'0').toUpperCase()}`;
  if(write.state==='rejected') return `Reg ${reg}: rejected${ADC_WRITABLE_NOW.has(reg)?'':' (needs BC widening)'}`;
  if(write.state==='readback_failed') return `Reg ${reg}: readback failed`;
  if(write.state==='i2c_error') return `Reg ${reg}: I²C error${write.status === null ? '' : ` 0x${write.status.toString(16).padStart(2,'0').toUpperCase()}`}`;
  if(write.state==='timeout') return `Reg ${reg}: reply timed out`;
  if(write.state==='queue_failed') return `Reg ${reg}: could not queue`;
  if(write.state==='not_sent') return `Reg ${reg}: not sent`;
  return '';
}
const UNCONFIRMED_WRITE_STATES = new Set(['queued','queued_unconfirmed','pending','timeout']);
export function adcCommandsBusy(snapshot:AdcSnapshot|null):boolean {
  return snapshot?.busy === true || Object.values(snapshot?.writes || {}).some(write => write.state === 'queued' || write.state === 'pending')
    || ['waiting','receiving'].includes(snapshot?.dump?.state || '');
}
export function adcDisplayByte(snapshot:AdcSnapshot|null,register:string):number|null {
  const key=register.toUpperCase(),write=snapshot?.writes?.[key];
  if(write&&UNCONFIRMED_WRITE_STATES.has(write.state)) return write.requested;
  return snapshot?.registers?.find(item=>item.register.toUpperCase()===key)?.value ?? null;
}
