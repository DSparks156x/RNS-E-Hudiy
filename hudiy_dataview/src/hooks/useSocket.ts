import { useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import { DiagnosticMessage, TabId, TabGroup, TabConfig } from '../types';
import { DataStore } from '../store/DataStore';

const TAB_CONFIG: TabConfig = {
    engine: [
        { module: 0x01, group: 102 },
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
        { module: 0x0A, group: 1, priority: 'low' },
        { module: 0x0A, group: 3 },
        { module: 0x0A, group: 5 },
    ],
};

function subscribe(socket: Socket, groups: TabGroup[], action: 'add' | 'remove') {
    groups.forEach((item) => {
        console.log(`${action.toUpperCase()} Group: Mod ${item.module} Grp ${item.group} Pri ${item.priority || 'normal'}`);
        socket.emit('toggle_group', { module: item.module, group: item.group, action, priority: item.priority || 'normal' });
    });
}

/**
 * useSocket now manages the connection and group toggling, but NO LONGER handles data state.
 * All incoming data is piped directly into the singleton DataStore, which is
 * read via useMotionValue subscriptions in the component tree.
 */
export function useSocket(currentTab: TabId) {
    const [socket, setSocket] = useState<Socket | null>(null);
    const currentTabRef = useRef<TabId>(currentTab);

    // Connect once on mount
    useEffect(() => {
        const s = io();
        setSocket(s);

        // --- Console Forwarding ---
        const originalLog = console.log;
        const originalWarn = console.warn;
        const originalError = console.error;

        console.log = (...args: any[]) => {
            originalLog(...args);
            socket.emit('client_log', { level: 'info', args });
        };
        console.warn = (...args: any[]) => {
            originalWarn(...args);
            socket.emit('client_log', { level: 'warn', args });
        };
        console.error = (...args: any[]) => {
            originalError(...args);
            socket.emit('client_log', { level: 'error', args });
        };

        socket.on('connect', () => {
            console.log('Connected to Backend');
            const groups = TAB_CONFIG[currentTabRef.current];
            if (groups) subscribe(s, groups, 'add');
        });

        s.on('diagnostic_update', (msg: unknown) => {
            DataStore.update([msg as DiagnosticMessage]);
        });

        s.on('diagnostic_batch', (batch: unknown) => {
            const msgs = batch as DiagnosticMessage[];
            if (!Array.isArray(msgs) || msgs.length === 0) return;
            DataStore.update(msgs);
        });

        return () => {
            s.disconnect();
        };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Manage subscriptions when tab changes
    useEffect(() => {
        if (!socket?.connected) return;

        // Only unsubscribe and subscribe if the tab actually changed
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

    return { socket };
}
