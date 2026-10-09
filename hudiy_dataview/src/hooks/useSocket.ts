import { useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import { DiagnosticMessage, VehicleValue, TabId, TabGroup, TabConfig } from '../types';
import { DataStore } from '../store/DataStore';
import { mockValues } from '../store/mockValues';

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
        socket.emit('toggle_group', { module: item.module, group: item.group, action, priority: item.priority || 'normal' });
    });
}

export const ENGINE_VALUES = [
    'engine.rpm', 'engine.maf', 'engine.ignition_timing',
    'engine.boost.actual_absolute', 'engine.boost.spec_absolute',
    'engine.fuel_rail.actual', 'engine.fuel_rail.spec', 'engine.fuel_pump_duty',
    'engine.injection_time', 'engine.oil_temperature', 'ambient.filtered_temperature',
    'engine.intake_temperature', 'engine.coolant_temperature',
    ...[1, 2, 3, 4].map(c => `engine.timing_retard.cylinder${c}`),
];

export const TRANSMISSION_VALUES = [
    ...[1, 2].flatMap(clutch => ['shaft_speed', 'specified_torque', 'valve_current', 'actual_pressure']
        .map(field => `transmission.clutch${clutch}.${field}`)),
    ...['1_3', '2_4', '5_n', '6_r'].map(gears => `transmission.selector.${gears}.travel_distance`),
    'transmission.fluid_temperature', 'transmission.module_temperature',
    'transmission.clutch_oil_temperature', 'transmission.idle_status',
];

export const AWD_VALUES = [
    'awd.oil_temperature', 'awd.plate_temperature', 'awd.supply_voltage', 'awd.oil_pressure',
    { id: 'awd.estimated_torque', allow_estimated: true },
    'awd.valve.opening', 'awd.valve.current', 'awd.can_output_signals', 'awd.vehicle_mode',
    'awd.slip_control', 'awd.operating_mode_fault', 'awd.commanded_torque', 'awd.slip_control_torque',
];

type ValueRequest = string | { id: string; allow_estimated?: boolean; allow_unverified?: boolean };
const TAB_VALUES: Record<string, ValueRequest[]> = {
    engine: ENGINE_VALUES, transmission: TRANSMISSION_VALUES, awd: AWD_VALUES,
};

export function useSocket(currentTab: TabId, dataLogValues: ValueRequest[] = []) {
    const [socket, setSocket] = useState<Socket | null>(null);
    const currentTabRef = useRef<TabId>(currentTab);
    const mockRef = useRef(false);
    const subscribedRef = useRef<TabGroup[]>([]);
    const applyRef = useRef<(tab: TabId) => void>(() => undefined);
    const lastAppliedRef = useRef('');
    const dataLogValuesRef = useRef(dataLogValues);
    dataLogValuesRef.current = dataLogValues;
    const dataLogValuesKey = JSON.stringify(dataLogValues);

    useEffect(() => {
        const s = io();
        setSocket(s);
        const original = { log: console.log, warn: console.warn, error: console.error };
        const forward = {
            log: (...args: unknown[]) => { original.log(...args); s.emit('client_log', { level: 'info', args }); },
            warn: (...args: unknown[]) => { original.warn(...args); s.emit('client_log', { level: 'warn', args }); },
            error: (...args: unknown[]) => { original.error(...args); s.emit('client_log', { level: 'error', args }); },
        };
        console.log = forward.log; console.warn = forward.warn; console.error = forward.error;
        const apply = (tab: TabId) => {
            const values = tab === 'data_logs' ? dataLogValuesRef.current : mockRef.current ? [] : TAB_VALUES[tab] || [];
            const signature = JSON.stringify([tab, mockRef.current, values]);
            if (signature === lastAppliedRef.current) return;
            lastAppliedRef.current = signature;
            DataStore.clearValues();
            subscribe(s, subscribedRef.current, 'remove');
            const groups = mockRef.current ? TAB_CONFIG[tab] || [] : [];
            subscribedRef.current = groups;
            subscribe(s, groups, 'add');
            s.emit('sync_values', { values });
        };
        applyRef.current = apply;
        s.on('connect', () => {
            subscribedRef.current = [];
            lastAppliedRef.current = '';
            DataStore.clearValues();
            apply(currentTabRef.current);
        });
        s.on('disconnect', () => DataStore.clearValues());
        s.on('status', (status: { mock_mode?: boolean }) => {
            if (status.mock_mode !== undefined && status.mock_mode !== mockRef.current) {
                mockRef.current = status.mock_mode;
                if (s.connected) apply(currentTabRef.current);
            }
        });
        s.on('values_batch', (values: VehicleValue[]) => {
            if (Array.isArray(values)) DataStore.updateValues(values);
        });
        s.on('values_response', (response: { status: string; error?: string; message?: string }) => {
            if (response.status === 'error') console.warn('Values service:', response.error || response.message);
        });
        const ingest = (msgs: DiagnosticMessage[]) => {
            DataStore.update(msgs);
            if (mockRef.current && currentTabRef.current !== 'data_logs') DataStore.updateValues(msgs.flatMap(mockValues));
        };
        s.on('diagnostic_update', (msg: DiagnosticMessage) => ingest([msg]));
        s.on('diagnostic_batch', (batch: DiagnosticMessage[]) => {
            if (Array.isArray(batch) && batch.length) ingest(batch);
        });
        const expiry = window.setInterval(() => DataStore.expireValues(), 100);
        const renewal = window.setInterval(() => {
            if (s.connected && (!mockRef.current || currentTabRef.current === 'data_logs')) {
                s.emit('sync_values', { values: currentTabRef.current === 'data_logs' ? dataLogValuesRef.current : TAB_VALUES[currentTabRef.current] || [] });
            }
        }, 5000);
        return () => {
            window.clearInterval(expiry);
            window.clearInterval(renewal);
            s.disconnect();
            if (console.log === forward.log) console.log = original.log;
            if (console.warn === forward.warn) console.warn = original.warn;
            if (console.error === forward.error) console.error = original.error;
        };
    }, []);

    useEffect(() => {
        if (currentTabRef.current !== currentTab) {
            currentTabRef.current = currentTab;
            if (socket?.connected) applyRef.current(currentTab);
        }
    }, [currentTab, socket]);
    useEffect(() => {
        if (socket?.connected && currentTabRef.current === 'data_logs') applyRef.current('data_logs');
    }, [dataLogValuesKey, socket]);
    return { socket };
}
