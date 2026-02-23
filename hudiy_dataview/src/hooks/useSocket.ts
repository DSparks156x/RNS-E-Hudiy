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
        { module: 0x02, group: 19, priority: 'low' },
    ],
    awd: [
        { module: 0x22, group: 1, priority: 'low' },
        { module: 0x22, group: 3 },
        { module: 0x22, group: 5 },
    ],
};

type DataMap = Record<string, DiagnosticMessage>;

function subscribe(socket: Socket, groups: TabGroup[], action: 'add' | 'remove') {
    groups.forEach((item) => {
        console.log(`${action.toUpperCase()} Group: Mod ${item.module} Grp ${item.group} Pri ${item.priority || 'normal'}`);
        socket.emit('toggle_group', { module: item.module, group: item.group, action, priority: item.priority || 'normal' });
    });
}

export function useSocket(currentTab: TabId) {
    const [data, setData] = useState<DataMap>({});
    const socketRef = useRef<Socket | null>(null);
    const currentTabRef = useRef<TabId>(currentTab);
    // Accumulate messages between animation frames, then flush once per frame
    const pendingRef = useRef<DataMap>({});
    const rafRef = useRef<number | null>(null);

    // Connect once on mount
    useEffect(() => {
        const socket = io();
        socketRef.current = socket;

        // Single RAF flush function — shared by both event handlers.
        // Schedules exactly one setData call per animation frame regardless of
        // how many socket messages arrive between frames.
        const scheduleFlush = () => {
            if (!rafRef.current) {
                rafRef.current = requestAnimationFrame(() => {
                    setData((prev) => ({ ...prev, ...pendingRef.current }));
                    pendingRef.current = {};
                    rafRef.current = null;
                });
            }
        };

        socket.on('connect', () => {
            console.log('Connected to Backend');
            const groups = TAB_CONFIG[currentTabRef.current];
            if (groups) subscribe(socket, groups, 'add');
        });

        socket.on('diagnostic_update', (msg: unknown) => {
            const m = msg as DiagnosticMessage;
            // Accumulate into pending — last value per key wins within the frame
            pendingRef.current[diagKey(m.module, m.group)] = m;
            scheduleFlush();
        });

        // Smoothing-mode batch: server sends all fresh groups in one emit instead of N.
        // Feed each group into the same pending accumulator so the RAF flush handles them.
        socket.on('diagnostic_batch', (batch: unknown) => {
            const msgs = batch as DiagnosticMessage[];
            if (!Array.isArray(msgs) || msgs.length === 0) return;
            for (const m of msgs) {
                pendingRef.current[diagKey(m.module, m.group)] = m;
            }
            scheduleFlush();
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
                    socket.emit('toggle_group', { module: item.module, group: item.group, action: 'remove', priority: item.priority || 'normal' });
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

    return { data, socket: socketRef.current };
}
