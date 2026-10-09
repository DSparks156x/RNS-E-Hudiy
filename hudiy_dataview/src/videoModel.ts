export interface VideoSettings { gamma: number; contrast: number; black_point: number; gain_r: number; gain_g: number; gain_b: number; }
export type VideoKey = keyof VideoSettings;
export interface VideoOutput { output: string; name?: string; description?: string; make?: string; model?: string; }
export interface VideoSnapshot { available: boolean; status: string; error?: string; outputs: VideoOutput[]; gamma_protocol?: boolean; active: boolean; output: string | null; settings: VideoSettings; saved_profile: { output: string | null; settings: VideoSettings } | null; profile_path?: string; profile_error?: string | null; }
export const VIDEO_DEFAULTS: VideoSettings = { gamma: 1, contrast: 1, black_point: 0, gain_r: 1, gain_g: 1, gain_b: 1 };
export const VIDEO_FIELDS: { key: VideoKey; label: string; help: string; min: number; max: number; step: number }[] = [
  { key: 'gamma', label: 'Gamma', help: 'Lift or darken the middle tones.', min: .5, max: 2, step: .01 },
  { key: 'contrast', label: 'Contrast', help: 'Spread or soften the difference between light and dark.', min: .5, max: 1.5, step: .01 },
  { key: 'black_point', label: 'Black point', help: 'Make the darkest tones reach black sooner.', min: 0, max: .1, step: .001 },
  { key: 'gain_r', label: 'Red gain', help: 'Adjust the red channel.', min: .5, max: 1.5, step: .01 },
  { key: 'gain_g', label: 'Green gain', help: 'Adjust the green channel.', min: .5, max: 1.5, step: .01 },
  { key: 'gain_b', label: 'Blue gain', help: 'Adjust the blue channel.', min: .5, max: 1.5, step: .01 },
];
export function validateVideoSettings(settings: VideoSettings): void {
  for (const field of VIDEO_FIELDS) {
    const value = settings[field.key];
    if (typeof value !== 'number' || !Number.isFinite(value) || value < field.min || value > field.max) throw new Error(`${field.label} must be between ${field.min} and ${field.max}.`);
  }
}
export function sameVideoSettings(a: VideoSettings, b: VideoSettings): boolean { return VIDEO_FIELDS.every(field => a[field.key] === b[field.key]); }
export function videoNumber(key: VideoKey, value: number): string { return value.toFixed(key === 'black_point' ? 3 : 2); }

/** At most one compositor request at a time. A newer drag replaces any waiting request. */
export class LatestVideoWriter<T, R> {
  private running = false;
  private closed = false;
  private waiting: { value: T; ticket: number } | null = null;
  constructor(private write: (value: T) => Promise<R>, private complete: (ticket: number, result: R | undefined, error: unknown) => void) {}
  submit(value: T, ticket: number): void { if (this.closed) return; this.waiting = { value, ticket }; void this.drain(); }
  close(): void { this.closed = true; this.waiting = null; }
  private async drain(): Promise<void> {
    if (this.running || this.closed) return;
    this.running = true;
    while (this.waiting && !this.closed) {
      const task = this.waiting; this.waiting = null;
      try { const result = await this.write(task.value); if (!this.closed) this.complete(task.ticket, result, undefined); }
      catch (error) { if (!this.closed) this.complete(task.ticket, undefined, error); }
    }
    this.running = false;
  }
}
