import { LogSample } from './model';

export const eventTime = (sample: LogSample) => sample.event_at ?? sample.received_at ?? sample.timestamp ?? 0;
export const validNumber = (sample: LogSample) => sample.status === 'ok' && typeof sample.value === 'number' && Number.isFinite(sample.value);

export function tracePath(entries: LogSample[], unit: string, since: number, until: number, x: (timestamp: number) => number, y: (value: number) => number): string {
  const intervals = entries.slice(1).map((sample, index) => eventTime(sample) - eventTime(entries[index])).filter(delta => delta > 0).sort((a, b) => a - b);
  const gap = Math.max(1, (intervals[Math.floor(intervals.length / 2)] || .5) * 3);
  let path = '', open = false, previous = -Infinity;
  for (const sample of entries) {
    const time = eventTime(sample);
    if (time < since || time > until || !validNumber(sample) || (sample.unit || '') !== unit) { open = false; continue; }
    const point = `${x(time).toFixed(2)} ${y(sample.value as number).toFixed(2)}`;
    if (open && time - previous <= gap) path += `L${point} `;
    else path += `M${point}l0.01 0 `; // Make an isolated valid sample visible without joining a gap.
    open = true; previous = time;
  }
  return path;
}
