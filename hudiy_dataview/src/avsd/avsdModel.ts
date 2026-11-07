/** Wording and value handling for the A/V over SD app. No React here. */
export interface SettingField {
  id: string; label: string; help: string; kind: 'range' | 'choice'; default: number;
  min?: number; max?: number; step?: number; unit?: string; scale?: number; decimals?: number;
  options?: { value: number; label: string }[];
}
export type SettingValues = Record<string, number>;
export interface SettingsSnapshot { fields: SettingField[]; values: SettingValues; saved: SettingValues; defaults: SettingValues; temporary: boolean; encflags_override: boolean; }

export interface ChainStatus {
  active: string; disabled: boolean;
  supervisor: { state: string; detail: string };
  verdict: string; stat: Record<string, number>; encoder_over: number;
}
export interface ReleaseInfo { version: string; branch?: string; built?: string; }
export interface Status {
  chain: ChainStatus;
  can: { present: boolean; up: boolean; listen_only: boolean };
  teensy: { repo: string | null; flashed: string | null; update_available: boolean; present: boolean };
  releases: { current: ReleaseInfo | null; previous: ReleaseInfo | null; check: { state: string; message?: string } | null; updates_with_rnse: boolean };
  decoder: { crc: string | null; old: boolean };
  portal: string[]; firmware_dir: string; can_change: boolean;
}
export interface Job { name: string; title: string; state: 'running' | 'ok' | 'failed'; message: string; lines: string[]; }
export interface FirmwareFile { name: string; size: number; sector: number | null; crc: string; problem: string | null; }

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-AVSD': '1' }, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data as T;
}

/** One line for the top of the Status page. tone picks the colour. */
export function chainSummary(chain: ChainStatus): { text: string; tone: 'good' | 'quiet' | 'bad' } {
  if (chain.disabled) return { text: 'Chain is off.', tone: 'quiet' };
  const { state, detail } = chain.supervisor;
  if (state === 'waiting') return { text: `Waiting for ${detail}.`, tone: 'bad' };
  if (state === 'restarting') return { text: `Restarting: ${detail}.`, tone: 'bad' };
  if (state === 'starting') return { text: 'Starting.', tone: 'quiet' };
  if (chain.active !== 'active') return { text: `Service is ${chain.active || 'not running'}.`, tone: 'bad' };
  if (chain.verdict === 'streaming') return { text: 'Streaming to the RNS-E.', tone: 'good' };
  if (chain.verdict === 'not_on_tv') return { text: 'Running. The RNS-E is not on TV.', tone: 'quiet' };
  if (chain.verdict === 'no_frames') return { text: 'No frames from the encoder.', tone: 'bad' };
  return { text: 'Starting.', tone: 'quiet' };
}

export function canSummary(can: Status['can']): string {
  if (!can.present || !can.up) return 'can0 is down';
  return can.listen_only ? 'Ignition off (listen-only)' : 'Ready';
}

export function formatSetting(field: SettingField, value: number): string {
  if (field.kind === 'choice') return field.options?.find(option => option.value === value)?.label ?? String(value);
  return `${(value / (field.scale || 1)).toFixed(field.decimals || 0)} ${field.unit || ''}`.trim();
}

export function sameValues(a: SettingValues, b: SettingValues): boolean {
  return Object.keys(a).every(key => a[key] === b[key]);
}

export function flashTargets(names: string[], files: FirmwareFile[]): string {
  return names.map(name => {
    const sector = files.find(file => file.name === name)?.sector;
    return sector === null || sector === undefined ? name : `sector ${sector}`;
  }).join(', ');
}
