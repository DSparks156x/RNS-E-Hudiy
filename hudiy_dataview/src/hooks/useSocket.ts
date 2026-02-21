import { useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import { DiagnosticMessage, TabId, TabGroup, TabConfig, diagKey } from '../types';

const TAB_CONFIG: TabConfig = {
    engine: [
        { module: 0x01, group: 2 },
        { module: 0x01, group: 3 },
        { module: 0x01, group: 20 },
        { module: 0x01, group: 106 },
        { module: 0x01, group: 115 },
    ],
    transmission: [
        { module: 0x02, group: 11 },
        { module: 0x02, group: 12 },
        { module: 0x02, group: 16 },
        { module: 0x02, group: 19 },
    ],
    awd: [
        { module: 0x22, group: 1 },
        { module: 0x22, group: 3 },
        { module: 0x22, group: 5 },
    ],
};

const RX_WINDOW_MS = 2000;
const FALLBACK_INTERVAL_MS = 200;
const MIN_INTERVAL_MS = 50;
const MAX_INTERVAL_MS = 500;

type DataMap = Record<string, DiagnosticMessage>;

function subscribe(socket: Socket, groups: TabGroup[], action: 'add' | 'remove') {
    groups.forEach((item) => {
        console.log(`${action.toUpperCase()} Group: Mod ${item.module} Grp ${item.group}`);
        socket.emit('toggle_group', { module: item.module, group: item.group, action });
    });
}

export function useSocket(currentTab: TabId) {
    const [data, setData] = useState<DataMap>({});
    const [intervalMs, setIntervalMs] = useState<number>(FALLBACK_INTERVAL_MS);
    const socketRef = useRef<Socket | null>(null);
    const currentTabRef = useRef<TabId>(currentTab);
    // Accumulate messages between animation frames, then flush once per frame
    const pendingRef = useRef<DataMap>({});
    const rafRef = useRef<number | null>(null);
    // Rolling window of message timestamps for rate calculation
    const rxTimestampsRef = useRef<number[]>([]);

    // Connect once on mount
    useEffect(() => {
        const socket = io();
        socketRef.current = socket;

        socket.on('connect', () => {
            console.log('Connected to Backend');
            const groups = TAB_CONFIG[currentTabRef.current];
            if (groups) subscribe(socket, groups, 'add');
        });

        socket.on('diagnostic_update', (msg: unknown) => {
            const m = msg as DiagnosticMessage;
            // Accumulate into pending — last value per key wins within the frame
            pendingRef.current[diagKey(m.module, m.group)] = m;

            // Record timestamp for RX rate measurement
            const now = performance.now();
            rxTimestampsRef.current.push(now);

            // Schedule a single flush on the next animation frame if not already pending
            if (!rafRef.current) {
                rafRef.current = requestAnimationFrame(() => {
                    setData((prev) => ({ ...prev, ...pendingRef.current }));
                    pendingRef.current = {};
                    rafRef.current = null;

                    // Compute average interval from the rolling 2-second window
                    const cutoff = performance.now() - RX_WINDOW_MS;
                    const ts = rxTimestampsRef.current.filter((t) => t >= cutoff);
                    rxTimestampsRef.current = ts;

                    if (ts.length >= 2) {
                        const totalSpan = ts[ts.length - 1] - ts[0];
                        const avgInterval = totalSpan / (ts.length - 1);
                        const clamped = Math.min(MAX_INTERVAL_MS, Math.max(MIN_INTERVAL_MS, avgInterval));
                        setIntervalMs(Math.round(clamped));
                    }
                });
            }
        });

        return () => {
            if (rafRef.current) cancelAnimationFrame(rafRef.current);
            socket.disconnect();
        };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Manage subscriptions when tab changes
    useEffect(() => {
        const socket = socketRef.current;
        if (!socket?.connected) return;

        // Only unsubscribe and subscribe if the tab actually changed
        // (or if this is the initial connection run managed by the connect handler)
        if (currentTabRef.current !== currentTab) {
            // Unsubscribe from the previously active tab's groups
            const prevGroups = TAB_CONFIG[currentTabRef.current];
            if (prevGroups) {
                prevGroups.forEach((item) => {
                    socket.emit('toggle_group', { module: item.module, group: item.group, action: 'remove' });
                });
            }

            // Subscribe to the new tab's groups
            const newGroups = TAB_CONFIG[currentTab];
            if (newGroups) {
                subscribe(socket, newGroups, 'add');
            }

            currentTabRef.current = currentTab;
        }
    }, [currentTab]);

    return { data, intervalMs };
}
