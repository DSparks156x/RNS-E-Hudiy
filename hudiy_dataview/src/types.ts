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
}

/** Maps tab IDs to their subscribed groups. */
export type TabConfig = Record<string, TabGroup[]>;

export type TabId = 'engine' | 'transmission' | 'awd';

/** Key used to store/look up a diagnostic message: "mod:grp" */
export function diagKey(module: number | string, group: number): string {
    return `${module}:${group}`;
}
