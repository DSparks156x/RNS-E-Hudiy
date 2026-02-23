import { DiagnosticMessage } from '../types';

type Listener = () => void;

class Store {
    private data: Record<string, DiagnosticMessage> = {};
    private listeners: Set<Listener> = new Set();
    // We can track individual value listeners for tighter updates if needed,
    // but a single global subscribe is usually fast enough when components simply read from the store,
    // since they are reading raw refs and returning motion values, we actually only need the motion value to update.
    // Wait, right, we want motion values! Let's do a central motion value store.

    // Actually, let's keep it simple: the store holds raw data.
    // We'll provide a hook `useLiveValue(groupKey, index)` that subscribes to specific keys.
    private valueListeners: Map<string, Set<(val: number | string) => void>> = new Map();

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
