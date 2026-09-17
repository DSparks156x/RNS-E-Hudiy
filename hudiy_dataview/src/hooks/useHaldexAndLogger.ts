import { useState, useEffect, useCallback } from 'react';
import { Socket } from 'socket.io-client';
import { HaldexStatus, LoggerStatus } from '../types';

export function useHaldexAndLogger(socket: Socket | null) {
    const [haldex, setHaldex] = useState<HaldexStatus>({
        status: 'offline',
        desired_mode: 0,
        desired_name: 'Stock',
        active_mode: null,
        active_name: null,
        token_ok: false,
        b08_torque_nm: 0,
        a7c_slip_nm: 0,
        a72_ceiling_nm: 0,
        yaw_model_counts: 0,
        hold_a7e: 0,
        last_telemetry_age: null,
        last_switch_time: 0,
    });

    const [logger, setLogger] = useState<LoggerStatus>({
        recording: false,
        profile: 'haldex',
        available_profiles: [],
        measuring_groups: [],
        output_path: '',
        frames_received: 0,
        rows_written: 0,
        markers_logged: 0,
        dropped_rows: 0,
        uptime_sec: 0,
        last_error: '',
        haldex_mode: 0,
        b08_torque_nm: 0,
        a7c_slip_torque_nm: 0,
    });

    useEffect(() => {
        if (!socket) return;

        const onHaldexUpdate = (data: HaldexStatus) => {
            if (data) setHaldex(data);
        };

        const onLoggerUpdate = (data: LoggerStatus) => {
            if (data) setLogger(data);
        };

        socket.on('haldex_update', onHaldexUpdate);
        socket.on('logger_update', onLoggerUpdate);

        // Initial fetch
        socket.emit('get_haldex_status');
        socket.emit('get_logger_status');

        const pollIvl = setInterval(() => {
            socket.emit('get_haldex_status');
            if (logger.recording) {
                socket.emit('get_logger_status');
            }
        }, 1000);

        return () => {
            socket.off('haldex_update', onHaldexUpdate);
            socket.off('logger_update', onLoggerUpdate);
            clearInterval(pollIvl);
        };
    }, [socket, logger.recording]);

    const setMode = useCallback((mode: number) => {
        socket?.emit('set_haldex_mode', { mode });
    }, [socket]);

    const cycleMode = useCallback(() => {
        socket?.emit('cycle_haldex_mode');
    }, [socket]);

    const startLogging = useCallback((outputPath?: string, profile = 'haldex') => {
        socket?.emit('start_logger', { output: outputPath, profile });
    }, [socket]);

    const stopLogging = useCallback(() => {
        socket?.emit('stop_logger');
    }, [socket]);

    const addMarker = useCallback((note: string) => {
        socket?.emit('add_logger_marker', { note });
    }, [socket]);

    return {
        haldex,
        logger,
        setMode,
        cycleMode,
        startLogging,
        stopLogging,
        addMarker,
    };
}
