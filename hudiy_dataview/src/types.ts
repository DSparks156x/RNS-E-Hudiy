/** A single measured value from a diagnostic group. */
export interface DiagnosticValue {
    value: number | string;
    unit: string;
}

/** Payload broadcast by the server on the 'diagnostic_update' event. */
export interface DiagnosticMessage {
    module: number | string;
    group: number;
    data: DiagnosticValue[];
}

/** A single module+group pair that a tab subscribes to. */
export interface TabGroup {
    module: number;
    group: number;
    priority?: 'low' | 'normal';
}

/** Maps tab IDs to their subscribed groups. */
export type TabConfig = Record<string, TabGroup[]>;

export type TabId = 'engine' | 'transmission' | 'awd' | 'diagnostics';

/** Key used to store/look up a diagnostic message: "mod:grp" */
export function diagKey(module: number | string, group: number): string {
    return `${module}:${group}`;
}

export interface HaldexStatus {
    status: 'synced' | 'switching' | 'reconciling' | 'offline';
    desired_mode: number;
    desired_name: string;
    active_mode: number | null;
    active_name: string | null;
    token_ok: boolean;
    b08_torque_nm: number;
    a7c_slip_nm: number;
    a72_ceiling_nm: number;
    yaw_model_counts: number;
    hold_a7e: number;
    last_telemetry_age: number | null;
    last_switch_time: number;
}

export interface LoggerStatus {
    recording: boolean;
    profile: string;
    available_profiles: Array<{ name: string; description: string }>;
    measuring_groups: Array<{ module: number; group: number; priority: 'normal' | 'low' }>;
    output_path: string;
    frames_received: number;
    rows_written: number;
    markers_logged: number;
    dropped_rows: number;
    uptime_sec: number;
    last_error: string;
    haldex_mode: number;
    b08_torque_nm: number;
    a7c_slip_torque_nm: number;
}
