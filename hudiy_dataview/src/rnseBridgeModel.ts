export type RnseChannel = 'brightness' | 'lcd_brightness';
export interface RnseControlSnapshot {
  state: string; mode?: string; level: number | null; lcd_brightness: number | null;
  effective_lcd_brightness: number | null; source: 0 | 1 | 2;
  manual_overrides: { brightness: number | null; lcd_brightness: number | null };
  settings?: Record<string, unknown>; queued?: boolean; error?: string;
  source_evidence?: unknown; radio_active?: boolean; inhibited?: boolean;
  protocol_available?: boolean;
}
export const RNSE_CONTROL_PATHS = new Set([
  'rnse.auto_brightness.enabled', 'rnse.auto_brightness.day_brightness', 'rnse.auto_brightness.night_brightness',
  'rnse.auto_lcd_brightness.enabled', 'rnse.auto_lcd_brightness.day_brightness', 'rnse.auto_lcd_brightness.night_brightness',
  'rnse.manual_brightness', 'rnse.manual_lcd_brightness', 'rnse.source_label.enabled',
]);
export const sourceLabel = (source: number) => source === 1 ? 'CarPlay' : source === 2 ? 'Android Auto' : 'Hudiy';
export const lcdLabel = (value: number) => value === 0 ? 'Follow cluster' : value < 6 ? `${value} · effective 6` : `${value} / 100`;

/** A gesture changes a local draft. Its release, keyup and blur share one commit. */
export class ReleasedValue {
  private committed: number;
  private draft: number;
  constructor(value: number) { this.committed = value; this.draft = value; }
  sync(value: number) { this.committed = value; this.draft = value; }
  change(value: number) { this.draft = value; }
  release(): number | null {
    if (this.draft === this.committed) return null;
    this.committed = this.draft;
    return this.draft;
  }
  cancel(): number { this.draft = this.committed; return this.committed; }
}
