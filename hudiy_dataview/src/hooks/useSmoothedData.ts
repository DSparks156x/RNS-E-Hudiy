import { useRef } from 'react';
import { DiagnosticMessage, DiagnosticValue } from '../types';

type DataMap = Record<string, DiagnosticMessage>;

// Tune: 0.0 = no filtering (raw), 1.0 = never updates
// 0.4 = mild smoothing — takes ~3 updates to reach 90% of a new value
const EMA_ALPHA = 0.4;

/**
 * useSmoothedData (lightweight, no rAF)
 *
 * Applied once per socket update. Returns EMA-filtered data so values
 * change less abruptly. Visual smoothness for the gauges and bar fills
 * comes from CSS transitions (already set via --rx-interval) and Recharts'
 * built-in RadialBar animation — not from a 60fps render loop.
 */
export function useSmoothedData(
    data: DataMap,
    _intervalMs: number,
    enabled: boolean,
): DataMap {
    const emaRef = useRef<Record<string, number>>({});

    if (!enabled) return data;

    const result: DataMap = {};
    for (const groupKey of Object.keys(data)) {
        const msg = data[groupKey];
        const smoothed: DiagnosticValue[] = msg.data.map((dv, i) => {
            const rawNum =
                typeof dv.value === 'number' ? dv.value : parseFloat(dv.value as string);
            if (isNaN(rawNum)) return dv; // strings pass through

            const key = `${groupKey}:${i}`;
            const prev = emaRef.current[key] ?? rawNum;
            const ema = prev + EMA_ALPHA * (rawNum - prev);
            emaRef.current[key] = ema;
            return { ...dv, value: ema };
        });
        result[groupKey] = { ...msg, data: smoothed };
    }
    return result;
}
