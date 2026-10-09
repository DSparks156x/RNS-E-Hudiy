export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type ConfigDocument = { [key: string]: JsonValue };
export interface SettingMetadata { label?: string; help?: string; detailedHelp?: string; type?: string; options?: JsonValue[]; min?: number; max?: number; integer?: boolean; order?: number; }
export interface SettingSection { id: string; title: string; description?: string; root?: string; keys?: string[]; }
export interface Metadata { schema?: Record<string, SettingMetadata>; sections?: SettingSection[]; }
export interface ConfigTarget { id: string; label: string; filename: string; exists: boolean; }
export interface ConfigSnapshot { id: string; label: string; filename: string; document: ConfigDocument; revision: string; affected_services?: string[]; }
export interface SaveResult extends ConfigSnapshot { backup?: string; message?: string; }
export interface ManagedService { id: string; label: string; unit: string; active_state: string; sub_state: string; description?: string; can_control: boolean; error?: string; }
export interface SettingField { id: string; path: string; keys: string[]; value: JsonValue; metadata: SettingMetadata; section: string; }

export const RNSE_DEFAULTS = { auto_brightness: { enabled: false, day_brightness: 10, night_brightness: 5 }, manual_brightness: 10, manual_lcd_brightness: 0, auto_lcd_brightness: { enabled: false, day_brightness: 100, night_brightness: 6 }, source_label: { enabled: false } };
const object = (value: JsonValue | undefined): value is ConfigDocument => !!value && typeof value === 'object' && !Array.isArray(value);
function rnseDefaults(document: ConfigDocument): ConfigDocument {
  if ('rnse' in document && !object(document.rnse)) return document;
  const rnse = { ...RNSE_DEFAULTS, ...(document.rnse as ConfigDocument || {}) } as ConfigDocument;
  for (const group of ['auto_brightness', 'auto_lcd_brightness', 'source_label'] as const) {
    if (!(group in (document.rnse as ConfigDocument || {})) || object(rnse[group])) rnse[group] = { ...RNSE_DEFAULTS[group], ...(object(rnse[group]) ? rnse[group] : {}) };
  }
  return { ...document, rnse };
}

export function fieldsFor(document: ConfigDocument, metadata: Metadata, project = true): SettingField[] {
  const fields: SettingField[] = [];
  const walk = (value: JsonValue, path: string, keys: string[]) => {
    const known = project && Object.prototype.hasOwnProperty.call(metadata.schema || {}, path) ? metadata.schema?.[path] : undefined;
    if (value && !Array.isArray(value) && typeof value === 'object' && Object.keys(value).length && !known?.type?.startsWith('json')) {
      Object.entries(value).forEach(([key, child]) => walk(child, path ? `${path}.${key}` : key, [...keys, key]));
      return;
    }
    const section = project ? metadata.sections?.find(group => (group.root && (path === group.root || path.startsWith(`${group.root}.`))) || group.keys?.some(key => path === key || path.startsWith(`${key}.`))) : undefined;
    fields.push({ id: '/' + keys.map(key => key.replace(/~/g, '~0').replace(/\//g, '~1')).join('/'), path, keys, value, metadata: known || {}, section: section?.id || (project ? 'additional' : keys[0]) });
  };
  Object.entries(project ? rnseDefaults(document) : document).forEach(([key, value]) => walk(value, key, [key]));
  return fields.sort((a, b) => (a.metadata.order ?? Number.MAX_SAFE_INTEGER) - (b.metadata.order ?? Number.MAX_SAFE_INTEGER));
}

export function displayValue(value: JsonValue, metadata: SettingMetadata = {}): string { return typeof value === 'string' && !metadata.type?.startsWith('json') ? value : JSON.stringify(value); }
export function parseSetting(text: string, original: JsonValue, metadata: SettingMetadata = {}): JsonValue {
  let value: JsonValue;
  if (metadata.type?.startsWith('json') || original === null || Array.isArray(original) || typeof original === 'object') {
    try { value = JSON.parse(text) as JsonValue; } catch { throw new Error('Enter valid JSON.'); }
    if ((metadata.type === 'json-array' || Array.isArray(original)) && !Array.isArray(value)) throw new Error('Enter a JSON array.');
    if (original !== null && !Array.isArray(original) && typeof original === 'object' && (!value || Array.isArray(value) || typeof value !== 'object')) throw new Error('Enter a JSON object.');
  } else if (typeof original === 'number') {
    if (!text.trim()) throw new Error('Enter a number.');
    value = Number(text);
    if (!Number.isFinite(value)) throw new Error('Enter a finite number.');
    if (metadata.integer && !Number.isInteger(value)) throw new Error('Enter a whole number.');
    if (metadata.min !== undefined && value < metadata.min) throw new Error(`Minimum: ${metadata.min}.`);
    if (metadata.max !== undefined && value > metadata.max) throw new Error(`Maximum: ${metadata.max}.`);
  } else if (typeof original === 'boolean') {
    if (text !== 'true' && text !== 'false') throw new Error('Choose on or off.');
    value = text === 'true';
  } else value = text;
  const valid = (item: JsonValue): boolean => typeof item === 'number' ? Number.isFinite(item) : Array.isArray(item) ? item.every(valid) : item && typeof item === 'object' ? Object.values(item).every(valid) : true;
  if (!valid(value)) throw new Error('All numbers must be finite.');
  return value;
}

/** Preserve unknown keys; add defaults only within an explicitly edited RNS-E group. */
export function applyEdits(snapshot: ConfigDocument, fields: SettingField[], edits: Record<string, string>): ConfigDocument {
  const next = JSON.parse(JSON.stringify(snapshot)) as ConfigDocument;
  for (const field of fields) {
    const byId = Object.prototype.hasOwnProperty.call(edits, field.id);
    const byPath = Object.prototype.hasOwnProperty.call(edits, field.path);
    if (!byId && !byPath) continue;
    const value = parseSetting(byId ? edits[field.id] : edits[field.path], field.value, field.metadata);
    const parts = field.keys;
    let parent = next;
    for (let index = 0; index < parts.length - 1; index++) {
      const part = parts[index];
      if (!Object.prototype.hasOwnProperty.call(parent, part)) Object.defineProperty(parent, part, { value: {}, writable: true, enumerable: true, configurable: true });
      if (!object(parent[part])) throw new Error(`Cannot edit inside ${parts.slice(0, index + 1).join('.')}.`);
      if (parts[0] === 'rnse' && index === 1 && ['auto_brightness', 'auto_lcd_brightness', 'source_label'].includes(part)) {
        parent[part] = { ...RNSE_DEFAULTS[part as 'auto_brightness' | 'auto_lcd_brightness' | 'source_label'], ...parent[part] };
      }
      parent = parent[part] as ConfigDocument;
    }
    parent[parts[parts.length - 1]] = value;
  }
  return next;
}

export function changedCount(fields: SettingField[], edits: Record<string, string>): number {
  return fields.filter(field => {
    const byId = Object.prototype.hasOwnProperty.call(edits, field.id);
    const byPath = Object.prototype.hasOwnProperty.call(edits, field.path);
    return (byId || byPath) && (byId ? edits[field.id] : edits[field.path]) !== displayValue(field.value, field.metadata);
  }).length;
}
export class ManagementError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function managementRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/manage${path}`, init);
  let body: T & { error?: string; message?: string };
  try { body = await response.json(); } catch { throw new ManagementError(`Manager returned an invalid response (${response.status}).`, response.status); }
  if (!response.ok) throw new ManagementError(body.error || body.message || `Request failed (${response.status}).`, response.status);
  return body;
}
export function filesPortalUrl(location: Pick<Location, 'protocol' | 'hostname'>): string {
  const url = new URL(`${location.protocol}//${location.hostname.includes(':') ? `[${location.hostname.replace(/^\[|\]$/g, '')}]` : location.hostname}`);
  url.port = '5003'; url.pathname = '/files'; return url.toString();
}
