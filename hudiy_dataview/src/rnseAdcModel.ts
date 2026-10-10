export type AdcRegister = string;
export type AdcWriteState = 'queued' | 'queued_unconfirmed' | 'pending' | 'ok' | 'rejected' | 'i2c_error' | 'timeout' | 'queue_failed' | 'not_sent';
export interface AdcSnapshot {
  reply_id?: number | null; reply_configured?: boolean; inhibited?: boolean; radio_active?: boolean; state?: string;
  command_error?: string | null;
  busy?: boolean;
  identification?: AdcIdentification;
  registers?: Array<{ register: string; value: number | null; baseline: number | null; changed?: boolean; failed?: boolean }>;
  writes?: Record<string, { requested: number; readback: number | null; status: number | null; state: AdcWriteState }>;
  dump?: { state: string; received_sequences?: number[]; error?: string | null };
  defaults?: Record<string, number>; clamp_duration_default?: number | null;
}
export interface AdcIdentification {
  state: 'idle' | 'pending' | 'restoring' | 'identified' | 'unconfirmed' | 'error';
  chip: 'AD9985' | 'AD9883A' | 'unknown' | null;
  probe: { requested: number; readback: number | null; status: number | null; state: string } | null;
  restore: { requested: number; readback: number | null; status: number | null; state: string } | null;
  restore_confirmed: boolean; error: string | null;
}
export interface AdcPreset { [register: string]: number }
export const ADC_REG_DEFAULTS: AdcPreset = {
  '01': 0x3f, '02': 0x50, '03': 0x30, '04': 0x80, '05': 0x16, '06': 0x2f,
  '07': 0x70, '08': 0x70, '09': 0x70, '0A': 0x70, '0B': 0x7e, '0C': 0x7e,
  '0D': 0x7e, '0E': 0x2d, '0F': 0x2a, '10': 0, '11': 0x20, '12': 6, '13': 6, '24': 0x58,
};
export const ADC_WRITABLE = new Set(['03','04','05','06','08','09','0A','0B','0C','0D','11','12','13']);
export type AdcControlId = 'gainR' | 'gainG' | 'gainB' | 'offsetR' | 'offsetG' | 'offsetB' | 'phase' | 'vcoRange' | 'vcoCurrent' | 'clampPlacement' | 'clampDuration' | 'preCoast' | 'postCoast' | 'threshold';
export function encodeAdcControl(id: AdcControlId, value: number): { register: string; byte: number } {
  if (!Number.isInteger(value)) throw new RangeError('ADC values must be whole numbers.');
  const specs: Record<AdcControlId, { register: string; min: number; max: number; encode: (n:number)=>number }> = {
    gainR:{register:'08',min:0,max:255,encode:n=>n},gainG:{register:'09',min:0,max:255,encode:n=>n},gainB:{register:'0A',min:0,max:255,encode:n=>n},
    offsetR:{register:'0B',min:0,max:127,encode:n=>n<<1},offsetG:{register:'0C',min:0,max:127,encode:n=>n<<1},offsetB:{register:'0D',min:0,max:127,encode:n=>n<<1},
    phase:{register:'04',min:0,max:31,encode:n=>n<<3},vcoRange:{register:'03',min:0,max:3,encode:n=>n<<6},vcoCurrent:{register:'03',min:0,max:7,encode:n=>n<<3},
    clampPlacement:{register:'05',min:0,max:255,encode:n=>n},clampDuration:{register:'06',min:0,max:255,encode:n=>n},preCoast:{register:'12',min:0,max:255,encode:n=>n},postCoast:{register:'13',min:0,max:255,encode:n=>n},threshold:{register:'11',min:0,max:255,encode:n=>n},
  };
  const spec=specs[id]; if(value<spec.min||value>spec.max) throw new RangeError(`${id} must be ${spec.min}–${spec.max}.`);
  return {register:spec.register,byte:spec.encode(value)};
}
export const decodeAdcControl = (id: AdcControlId, byte: number): number => id.startsWith('offset') ? (byte >> 1) & 0x7f : id==='phase' ? (byte >> 3)&0x1f : id==='vcoRange' ? (byte>>6)&3 : id==='vcoCurrent' ? (byte>>3)&7 : byte;
export function encodeVco(range:number,current:number):number {
  if(!Number.isInteger(range)||range<0||range>3||!Number.isInteger(current)||current<0||current>7) throw new RangeError('VCO range and current are outside their supported bounds.');
  return (range<<6)|(current<<3);
}
export function validateClampWindow(placement:number, duration:number): boolean { return Number.isInteger(placement) && Number.isInteger(duration) && placement>=0 && duration>=0 && placement<=255 && duration<=255 && placement+duration<110; }
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
  if(write.state==='rejected') return `Reg ${reg}: rejected`;
  if(write.state==='i2c_error') return `Reg ${reg}: I²C error${write.status === null ? '' : ` 0x${write.status.toString(16).padStart(2,'0').toUpperCase()}`}`;
  if(write.state==='timeout') return `Reg ${reg}: reply timed out`;
  if(write.state==='queue_failed') return `Reg ${reg}: could not queue`;
  if(write.state==='not_sent') return `Reg ${reg}: not sent`;
  return '';
}
export function adcIdentificationMessage(result:AdcIdentification|undefined):string {
  if(!result||result.state==='idle') return 'Not run';
  if(result.state==='pending') return 'Probe sent · waiting for readback';
  if(result.state==='restoring') return 'Probe received · restoring register 1A';
  if(result.state==='unconfirmed'&&result.chip==null) return 'Unconfirmed (no reply)';
  if(result.state==='error'&&result.chip==null) return result.error||'Identification failed';
  const probe=result.probe?.readback==null?'—':`0x${result.probe.readback.toString(16).padStart(2,'0').toUpperCase()}`;
  const restore=result.restore_confirmed?'restore confirmed':`restore ${result.restore?.state||'unconfirmed'}`;
  return `${result.chip||'Unknown chip'} · read ${probe} · ${restore}${result.error?` · ${result.error}`:''}`;
}
const UNCONFIRMED_WRITE_STATES = new Set(['queued','queued_unconfirmed','pending','timeout']);
export function adcCommandsBusy(snapshot:AdcSnapshot|null):boolean {
  return snapshot?.busy === true || Object.values(snapshot?.writes || {}).some(write => write.state === 'queued' || write.state === 'pending')
    || ['waiting','receiving'].includes(snapshot?.dump?.state || '')
    || ['pending','restoring'].includes(snapshot?.identification?.state || '');
}
export function adcDisplayByte(snapshot:AdcSnapshot|null,register:string):number|null {
  const key=register.toUpperCase(),write=snapshot?.writes?.[key];
  if(write&&UNCONFIRMED_WRITE_STATES.has(write.state)) return write.requested;
  return snapshot?.registers?.find(item=>item.register.toUpperCase()===key)?.value ?? null;
}
