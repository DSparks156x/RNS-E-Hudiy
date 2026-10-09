import { DiagnosticMessage, VehicleValue } from '../types';

type Listener = () => void;

class Store {
    private data: Record<string, DiagnosticMessage> = {};
    private values: Record<string, { sample: VehicleValue; received: number; displayed: number | string }> = {};
    private listeners: Set<Listener> = new Set();
    // Motion values subscribe directly so telemetry does not render the whole app.
    private valueListeners: Map<string, Set<(val: number | string) => void>> = new Map();

    updateValues(batch: VehicleValue[], now = performance.now()) {
        for (const incoming of batch) {
            let sample = incoming;
            if (!sample || typeof sample.id !== 'string') continue;
            if (sample.status === 'ok' && typeof sample.value === 'number' && !Number.isFinite(sample.value)) {
                sample = { ...sample, status: 'invalid', value: null, quality: {
                    ...sample.quality, valid: false, reason: 'Non-finite source value' } };
            }
            // Snapshots/renewals may already exceed their acquisition age limit.
            // Publish only the final state, avoiding a healthy/stale flicker.
            if (this.isExpired(sample, 0)) sample = this.staleSample(sample);
            const usable = typeof sample.value === 'string' || typeof sample.value === 'number';
            const displayed = sample.status === 'ok' && usable ? sample.value! : '--';
            this.values[sample.id] = { sample, received: now, displayed };
            this.valueListeners.get(`value:${sample.id}[0]`)?.forEach(l => l(displayed));
        }
        this.expireValues(now);
    }

    expireValues(now = performance.now()) {
        for (const [id, entry] of Object.entries(this.values)) {
            const { sample } = entry;
            if (sample.status === 'ok' && this.isExpired(sample, now - entry.received)) {
                entry.displayed = '--';
                entry.sample = this.staleSample(sample);
                this.valueListeners.get(`value:${id}[0]`)?.forEach(l => l('--'));
            }
        }
    }

    private isExpired(sample: VehicleValue, elapsed: number) {
        return sample.status === 'ok' && typeof sample.max_age_ms === 'number' &&
            typeof sample.age_ms === 'number' && sample.age_ms + elapsed > sample.max_age_ms;
    }

    private staleSample(sample: VehicleValue): VehicleValue {
        return { ...sample, status: 'stale', quality: {
            ...sample.quality, valid: false, fresh: false, reason: 'Source stopped updating' } };
    }

    clearValues() {
        const ids = Object.keys(this.values);
        this.values = {};
        for (const id of ids) {
            this.valueListeners.get(`value:${id}[0]`)?.forEach(l => l('--'));
        }
    }

    getValue(id: string) { return this.values[id]?.sample; }

    update(batch: DiagnosticMessage[]) {
        batch.forEach((msg) => {
            const gkey = `${msg.module}:${msg.group}`;
            this.data[gkey] = msg;

            msg.data.forEach((val, i) => {
                const vKey = `${gkey}[${i}]`;
                const listeners = this.valueListeners.get(vKey);
                if (listeners) {
                    const raw = typeof val.value === 'number' ? val.value : (isNaN(parseFloat(val.value)) ? val.value : parseFloat(val.value));
                    listeners.forEach(l => l(raw));
                }
            });
        });
        this.emit();
    }

    getMsg(module_id: number, group: number) {
        return this.data[`${module_id}:${group}`];
    }

    getGroup(groupKey: string) {
        return this.data[groupKey];
    }

    // Subscribe to ANY change (useful for debugging, not for rendering components)
    subscribe(listener: Listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    // Subscribe to a specific value in a group
    subscribeValue(groupKey: string, index: number, listener: (val: number | string) => void) {
        const vKey = `${groupKey}[${index}]`;
        if (!this.valueListeners.has(vKey)) {
            this.valueListeners.set(vKey, new Set());
        }
        this.valueListeners.get(vKey)!.add(listener);

        // Fire immediately with current value if we have it
        const currentMsg = this.data[groupKey];
        if (groupKey.startsWith('value:')) {
            listener(this.values[groupKey.slice(6)]?.displayed ?? '--');
        }
        if (currentMsg && currentMsg.data[index]) {
            const val = currentMsg.data[index].value;
            const raw = typeof val === 'number' ? val : (isNaN(parseFloat(val)) ? val : parseFloat(val));
            listener(raw);
        }

        return () => {
            const set = this.valueListeners.get(vKey);
            if (set) {
                set.delete(listener);
                if (set.size === 0) this.valueListeners.delete(vKey);
            }
        };
    }

    private emit() {
        this.listeners.forEach((l) => l());
    }
}

export const DataStore = new Store();
