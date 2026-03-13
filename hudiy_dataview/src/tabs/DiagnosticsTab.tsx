import { useState, useEffect, useRef } from 'react';
import { useSocket } from '../hooks/useSocket';
import { useHudiyTheme } from '../hooks/useHudiyTheme';
import { Keypad } from '../components/Keypad';

interface FreezeFrameItem {
    label: string;
    value: any;
    unit?: string;
    known?: boolean;
}

interface DTC {
    code: string;
    code_dec: string;
    status: number;
    status_decoded?: string[];
    freeze_frame_raw?: string[];
    freeze_frame?: FreezeFrameItem[];
}

const KNOWN_MODULES = [
    { name: 'Engine', id: 0x01 },
    { name: 'Auto Trans', id: 0x02 },
    { name: 'ABS Brakes', id: 0x03 },
    { name: 'Instruments', id: 0x07 },
    { name: 'AWD', id: 0x0A },
    { name: 'CAN Gateway', id: 0x1F },
    { name: 'Door Elect, Driver', id: 0x22 },
    { name: 'Door Elect, Pass.', id: 0x23 },
    { name: 'Tire Pressure', id: 0x29 },
    { name: 'Steering wheel', id: 0x2A },
    { name: 'Auto HVAC', id: 0x2C },
    { name: 'Digital Radio', id: 0x4F },
    { name: 'Navigation', id: 0x52 },
];

const rememberedDiagnosticsGroups: Record<number, { g1: string, g2: string, g3: string }> = {};

export function DiagnosticsTab({ isActive = true }: { isActive?: boolean }) {
    // Use the socket hook to get the connection. We don't subscribe to fixed groups here.
    const { socket } = useSocket('diagnostics');
    const { theme } = useHudiyTheme(socket);

    const [selectedModule, setSelectedModule] = useState<number | null>(null);
    const [dtcs, setDtcs] = useState<DTC[]>([]);
    const [loadingDTCs, setLoadingDTCs] = useState(false);
    const [dtcError, setDtcError] = useState<string | null>(null);

    // Group Subscriptions
    const [group1, setGroup1] = useState<string>('');
    const [group2, setGroup2] = useState<string>('');
    const [group3, setGroup3] = useState<string>('');
    const [groupData, setGroupData] = useState<Record<string, any>>({});

    // Keypad State
    const [activeKeypad, setActiveKeypad] = useState<1 | 2 | 3 | null>(null);
    const [tempKeypadVal, setTempKeypadVal] = useState<string>('');

    const activeModuleRef = useRef<number | null>(null);
    const activeGroupsRef = useRef<{ g1: string, g2: string, g3: string }>({ g1: '', g2: '', g3: '' });

    useEffect(() => {
        activeModuleRef.current = selectedModule;
    }, [selectedModule]);

    useEffect(() => {
        activeGroupsRef.current = { g1: group1, g2: group2, g3: group3 };
    }, [group1, group2, group3]);

    useEffect(() => {
        if (!socket) return;

        const onDtcReport = (data: any) => {
            if (selectedModule !== null && data.module === selectedModule && data.type === 'dtc_report') {
                if (data.error) {
                    setDtcError(data.error);
                } else {
                    setDtcs(data.dtcs || []);
                    setDtcError(null);
                }
                setLoadingDTCs(false);
            }
        };

        const onDiagnosticUpdate = (data: any) => {
            if (selectedModule !== null && data.module === selectedModule) {
                setGroupData(prev => ({
                    ...prev,
                    [data.group]: data.data
                }));
            }
        };

        const onBatchUpdate = (batch: any[]) => {
            batch.forEach(data => onDiagnosticUpdate(data));
        };

        socket.on('diagnostic_update', onDiagnosticUpdate);
        socket.on('diagnostic_batch', onBatchUpdate);
        socket.on('dtc_report', onDtcReport); // Need to register this channel? Or is it part of the others? 
        // Wait, app.py uses `namespace='/'` and standard emit. I will add a standard emit for dtc_report.
        // Wait, app.py publishes via ZMQ, and we didn't add the socketio relay for it! I need to fix app.py!

        return () => {
            socket.off('diagnostic_update', onDiagnosticUpdate);
            socket.off('diagnostic_batch', onBatchUpdate);
            socket.off('dtc_report', onDtcReport);
        };
    }, [socket, selectedModule]);

    // Unsubscribe from old groups when component unmounts
    useEffect(() => {
        return () => {
            const mod = activeModuleRef.current;
            if (mod !== null && socket) {
                const { g1, g2, g3 } = activeGroupsRef.current;
                rememberedDiagnosticsGroups[mod] = { g1, g2, g3 };

                if (g1 && !isNaN(parseInt(g1))) socket.emit('toggle_group', { action: 'remove', module: mod, group: parseInt(g1) });
                if (g2 && !isNaN(parseInt(g2))) socket.emit('toggle_group', { action: 'remove', module: mod, group: parseInt(g2) });
                if (g3 && !isNaN(parseInt(g3))) socket.emit('toggle_group', { action: 'remove', module: mod, group: parseInt(g3) });
            }
        };
    }, [socket]);

    // Unsubscribe when tab is hidden, re-subscribe when shown
    useEffect(() => {
        const mod = activeModuleRef.current;
        if (socket && mod !== null) {
            const { g1, g2, g3 } = activeGroupsRef.current;
            if (isActive) {
                if (g1 && !isNaN(parseInt(g1))) socket.emit('toggle_group', { action: 'add', module: mod, group: parseInt(g1), priority: 'normal' });
                if (g2 && !isNaN(parseInt(g2))) socket.emit('toggle_group', { action: 'add', module: mod, group: parseInt(g2), priority: 'normal' });
                if (g3 && !isNaN(parseInt(g3))) socket.emit('toggle_group', { action: 'add', module: mod, group: parseInt(g3), priority: 'normal' });
            } else {
                if (g1 && !isNaN(parseInt(g1))) socket.emit('toggle_group', { action: 'remove', module: mod, group: parseInt(g1) });
                if (g2 && !isNaN(parseInt(g2))) socket.emit('toggle_group', { action: 'remove', module: mod, group: parseInt(g2) });
                if (g3 && !isNaN(parseInt(g3))) socket.emit('toggle_group', { action: 'remove', module: mod, group: parseInt(g3) });
            }
        }
    }, [isActive, socket]);

    const requestDTCs = () => {
        if (!socket || selectedModule === null) return;
        setLoadingDTCs(true);
        setDtcs([]);
        setDtcError(null);
        socket.emit('request_dtcs', { module: selectedModule });
    };

    const requestClearDTCs = () => {
        if (!socket || selectedModule === null) return;
        setLoadingDTCs(true);
        setDtcs([]);
        setDtcError(null);
        socket.emit('clear_dtcs', { module: selectedModule });
    };

    const toggleSubscription = (oldGrp: string, newGrp: string) => {
        if (!socket || selectedModule === null) return;

        const oldId = parseInt(oldGrp);
        const newId = parseInt(newGrp);

        if (!isNaN(oldId)) {
            socket.emit('toggle_group', { action: 'remove', module: selectedModule, group: oldId });
            setGroupData(prev => {
                const next = { ...prev };
                delete next[oldId];
                return next;
            });
        }
        if (!isNaN(newId)) {
            socket.emit('toggle_group', { action: 'add', module: selectedModule, group: newId, priority: 'normal' });
        }
    };

    const handleInputClick = (groupNum: 1 | 2 | 3, currentVal: string) => {
        setActiveKeypad(groupNum);
        setTempKeypadVal(currentVal);
    };

    const handleKeypadClose = () => {
        if (activeKeypad === 1) {
            toggleSubscription(group1, tempKeypadVal);
            setGroup1(tempKeypadVal);
        } else if (activeKeypad === 2) {
            toggleSubscription(group2, tempKeypadVal);
            setGroup2(tempKeypadVal);
        } else if (activeKeypad === 3) {
            toggleSubscription(group3, tempKeypadVal);
            setGroup3(tempKeypadVal);
        }
        setActiveKeypad(null);
    };

    const renderGroupFields = (_grpId: string, values: any[]) => {
        if (!values || values.length === 0) return <div style={styles.emptyGroup}>No Data</div>;
        return (
            <div style={styles.groupFields}>
                {values.slice(0, 4).map((v, i) => {
                    let dispVal = String(v.value);
                    if (typeof v.value === 'number') {
                        // For numbers, try to keep some precision but stay within 5 chars
                        if (dispVal.length > 5) {
                            const fixed = v.value.toFixed(1);
                            dispVal = fixed.length <= 5 ? fixed : Math.round(v.value).toString();
                        }
                    }
                    dispVal = dispVal.substring(0, 5);

                    return (
                        <div key={i} style={{ ...styles.fieldBox, border: `1px solid ${theme.outlineVariant || 'rgba(255,255,255,0.1)'}` }}>
                            <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: theme.onSurface, fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                                {dispVal}
                            </div>
                            <div style={{ fontSize: '0.8rem', color: theme.onSurfaceVariant || '#aaa', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', width: '100%', textAlign: 'center' }}>
                                {v.unit || '-'}
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    };

    if (selectedModule === null) {
        return (
            <section id="diagnostics" className="tab-content" style={{ color: theme.onSurface, padding: '10px', height: '100%', display: 'flex', flexDirection: 'column' }}>
                <div style={styles.moduleGrid}>
                    {KNOWN_MODULES.map(mod => (
                        <button
                            key={mod.id}
                            style={{ ...styles.moduleBtn, backgroundColor: theme.primaryContainer, color: theme.onPrimaryContainer }}
                            onClick={() => {
                                setSelectedModule(mod.id);
                                const saved = rememberedDiagnosticsGroups[mod.id] || { g1: '', g2: '', g3: '' };
                                setGroup1(saved.g1);
                                setGroup2(saved.g2);
                                setGroup3(saved.g3);
                                setGroupData({});
                                setDtcs([]);
                                setDtcError(null);

                                if (saved.g1 && !isNaN(parseInt(saved.g1))) socket?.emit('toggle_group', { action: 'add', module: mod.id, group: parseInt(saved.g1), priority: 'normal' });
                                if (saved.g2 && !isNaN(parseInt(saved.g2))) socket?.emit('toggle_group', { action: 'add', module: mod.id, group: parseInt(saved.g2), priority: 'normal' });
                                if (saved.g3 && !isNaN(parseInt(saved.g3))) socket?.emit('toggle_group', { action: 'add', module: mod.id, group: parseInt(saved.g3), priority: 'normal' });
                            }}
                        >
                            <span style={{ fontSize: '1.2rem', fontWeight: 'bold', lineHeight: 1.1, wordBreak: 'break-word' }}>{mod.name}</span>
                            <span style={{ fontSize: '1rem', opacity: 0.8 }}>0x{mod.id.toString(16).padStart(2, '0').toUpperCase()}</span>
                        </button>
                    ))}
                </div>
            </section>
        );
    }

    return (
        <section id="diagnostics" className="tab-content" style={{ color: theme.onSurface, padding: '10px', height: '100%', display: 'flex', flexDirection: 'column', flexGrow: 1, minHeight: 0, boxSizing: 'border-box' }}>
            {/* Header / Module Selection */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', flexShrink: 0 }}>
                <button
                    style={{ ...styles.actionBtn, backgroundColor: theme.surfaceDim || 'rgba(0,0,0,0.3)', color: theme.onSurface, border: 'none', display: 'flex', alignItems: 'center', gap: '6px' }}
                    onClick={() => {
                        if (selectedModule !== null) {
                            rememberedDiagnosticsGroups[selectedModule] = { g1: group1, g2: group2, g3: group3 };
                            if (group1 && !isNaN(parseInt(group1))) socket?.emit('toggle_group', { action: 'remove', module: selectedModule, group: parseInt(group1) });
                            if (group2 && !isNaN(parseInt(group2))) socket?.emit('toggle_group', { action: 'remove', module: selectedModule, group: parseInt(group2) });
                            if (group3 && !isNaN(parseInt(group3))) socket?.emit('toggle_group', { action: 'remove', module: selectedModule, group: parseInt(group3) });
                        }
                        setSelectedModule(null);
                        setGroup1(''); setGroup2(''); setGroup3('');
                        setGroupData({});
                        setDtcs([]);
                        setDtcError(null);
                    }}
                >
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="15 18 9 12 15 6"></polyline>
                    </svg>
                    Back
                </button>

                <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    <h2 style={{ margin: 0, opacity: 0.9 }}>
                        {KNOWN_MODULES.find(m => m.id === selectedModule)?.name || 'Unknown'}
                    </h2>
                    <span style={{ fontSize: '0.9rem', opacity: 0.7, marginTop: '2px' }}>
                        0x{selectedModule.toString(16).padStart(2, '0').toUpperCase()}
                    </span>
                </div>

                <div style={{ display: 'flex', gap: '10px' }}>
                    <button
                        style={{ ...styles.actionBtn, backgroundColor: loadingDTCs ? theme.surfaceVariant : 'rgba(255, 60, 60, 0.8)' }}
                        onClick={requestClearDTCs}
                        disabled={loadingDTCs}
                    >
                        Clear DTCs
                    </button>
                    <button
                        style={{ ...styles.actionBtn, backgroundColor: loadingDTCs ? theme.surfaceVariant : theme.primaryContainer, color: theme.onPrimaryContainer }}
                        onClick={requestDTCs}
                        disabled={loadingDTCs}
                    >
                        {loadingDTCs ? 'Reading...' : 'Read DTCs'}
                    </button>
                </div>
            </div>

            {/* Content Area split into DTCs and Measuring Groups */}
            <div style={{ display: 'flex', flexGrow: 1, gap: '15px', minHeight: 0, height: '100%' }}>

                {/* Left Side: DTCs (and Keypad overlay) */}
                <div style={{ ...styles.panel, backgroundColor: theme.surfaceContainer || 'rgba(0,0,0,0.3)', flexGrow: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%', boxSizing: 'border-box', position: 'relative' }}>
                    <h3 style={{ marginTop: 0, borderBottom: `1px solid ${theme.outlineVariant || 'rgba(255,255,255,0.1)'}`, paddingBottom: '8px', flexShrink: 0 }}>Fault Codes</h3>
                    <div className="pretty-scroll" style={{ flexGrow: 1, minHeight: 0, paddingRight: '4px' }}>
                        {dtcs.length === 0 && !loadingDTCs && !dtcError && <div style={{ padding: '10px', opacity: 0.7 }}>No fault codes found.</div>}
                        {loadingDTCs && <div style={{ padding: '10px', opacity: 0.7 }}>Querying module...</div>}
                        {dtcError && <div style={{ padding: '10px', color: 'rgba(255, 60, 60, 0.9)' }}>Error: {dtcError}</div>}
                        {dtcs.map((dtc, i) => (
                            <div key={i} style={{ padding: '10px', borderBottom: `1px solid ${theme.outlineVariant || 'rgba(255,255,255,0.1)'}`, display: 'flex', flexDirection: 'column' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <div>
                                        <span style={{ fontFamily: 'monospace', fontSize: '1.2rem', fontWeight: 'bold', marginRight: '6px' }}>{dtc.code_dec}</span>
                                        <span style={{ fontSize: '0.9rem', opacity: 0.7 }}>(Hex: {dtc.code})</span>
                                    </div>
                                    <span style={{ fontSize: '0.9rem', opacity: 0.7 }}>
                                        {dtc.status_decoded ? dtc.status_decoded.join(', ') : `Status: 0x${dtc.status.toString(16).padStart(2, '0')}`}
                                    </span>
                                </div>
                                {(() => {
                                    if (dtc.freeze_frame && dtc.freeze_frame.length > 0) {
                                        return (
                                            <div style={{ marginTop: '8px', padding: '10px', backgroundColor: theme.surfaceVariant || 'rgba(0,0,0,0.4)', borderRadius: '12px', border: `1px solid ${theme.outlineVariant || 'rgba(255,255,255,0.1)'}` }}>
                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px' }}>
                                                    {dtc.freeze_frame.map((item, ffIdx) => (
                                                        <div key={ffIdx} style={{ display: 'flex', flexDirection: 'column' }}>
                                                            <span style={{ fontSize: '0.75rem', opacity: 0.6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{item.label}</span>
                                                            <span style={{ fontSize: '1.1rem', fontWeight: 'bold', color: theme.primary }}>
                                                                {item.value} {item.unit || ''}
                                                            </span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        );
                                    } else if (dtc.freeze_frame_raw && dtc.freeze_frame_raw.length > 0) {
                                        return (
                                            <div style={{ marginTop: '8px', padding: '6px', backgroundColor: theme.surfaceDim || 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                                                <span style={{ fontSize: '0.8rem', opacity: 0.6, display: 'block', marginBottom: '4px' }}>Freeze Frame (Raw Hex)</span>
                                                <span style={{ fontFamily: 'monospace', fontSize: '0.9rem', color: theme.primary, wordBreak: 'break-all' }}>
                                                    {dtc.freeze_frame_raw.join(' ')}
                                                </span>
                                            </div>
                                        );
                                    }
                                    return null;
                                })()}
                            </div>
                        ))}
                    </div>
                    {activeKeypad !== null && (
                        <Keypad
                            value={tempKeypadVal}
                            onChange={setTempKeypadVal}
                            onClose={handleKeypadClose}
                            onSubmit={(nextVal) => {
                                if (activeKeypad === 1) {
                                    toggleSubscription(group1, nextVal);
                                    setGroup1(nextVal);
                                } else if (activeKeypad === 2) {
                                    toggleSubscription(group2, nextVal);
                                    setGroup2(nextVal);
                                } else if (activeKeypad === 3) {
                                    toggleSubscription(group3, nextVal);
                                    setGroup3(nextVal);
                                }
                            }}
                        />
                    )}
                </div>

                {/* Right Side: RT Data */}
                <div style={{ ...styles.panel, backgroundColor: theme.surfaceContainer || 'rgba(0,0,0,0.3)', flexGrow: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%', boxSizing: 'border-box' }}>
                    <h3 style={{ marginTop: 0, borderBottom: `1px solid ${theme.outlineVariant || 'rgba(255,255,255,0.1)'}`, paddingBottom: '8px', flexShrink: 0 }}>Measuring Groups</h3>

                    <div className="pretty-scroll" style={{ display: 'flex', flexDirection: 'column', gap: '10px', flexGrow: 1, minHeight: 0, height: '100%', paddingRight: '4px' }}>
                        {/* Group 1 */}
                        <div style={styles.groupRow}>
                            <input
                                type="text"
                                readOnly
                                placeholder="Grp 1"
                                value={activeKeypad === 1 ? tempKeypadVal : group1}
                                onClick={() => handleInputClick(1, group1)}
                                style={{ ...styles.groupInput, backgroundColor: activeKeypad === 1 ? 'rgba(255,255,255,0.2)' : theme.surfaceDim || 'rgba(255,255,255,0.1)', color: theme.onSurface, cursor: 'pointer' }}
                            />
                            <div style={{ flexGrow: 1, display: 'flex' }}>{renderGroupFields(group1, groupData[group1])}</div>
                        </div>

                        {/* Group 2 */}
                        <div style={styles.groupRow}>
                            <input
                                type="text"
                                readOnly
                                placeholder="Grp 2"
                                value={activeKeypad === 2 ? tempKeypadVal : group2}
                                onClick={() => handleInputClick(2, group2)}
                                style={{ ...styles.groupInput, backgroundColor: activeKeypad === 2 ? 'rgba(255,255,255,0.2)' : theme.surfaceDim || 'rgba(255,255,255,0.1)', color: theme.onSurface, cursor: 'pointer' }}
                            />
                            <div style={{ flexGrow: 1, display: 'flex' }}>{renderGroupFields(group2, groupData[group2])}</div>
                        </div>

                        {/* Group 3 */}
                        <div style={styles.groupRow}>
                            <input
                                type="text"
                                readOnly
                                placeholder="Grp 3"
                                value={activeKeypad === 3 ? tempKeypadVal : group3}
                                onClick={() => handleInputClick(3, group3)}
                                style={{ ...styles.groupInput, backgroundColor: activeKeypad === 3 ? 'rgba(255,255,255,0.2)' : theme.surfaceDim || 'rgba(255,255,255,0.1)', color: theme.onSurface, cursor: 'pointer' }}
                            />
                            <div style={{ flexGrow: 1, display: 'flex' }}>{renderGroupFields(group3, groupData[group3])}</div>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    );
}

const styles: Record<string, React.CSSProperties> = {
    actionBtn: {
        padding: '10px 20px',
        fontSize: '1.2rem',
        borderRadius: '8px',
        border: 'none',
        color: 'white',
        cursor: 'pointer',
        fontWeight: 'bold',
        minWidth: 'min(120px, 20vw)',
    },
    panel: {
        borderRadius: '16px',
        padding: '12px',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0
    },
    groupRow: {
        display: 'flex',
        alignItems: 'stretch',
        gap: '10px',
        flexGrow: 1,
        minHeight: 0
    },
    groupInput: {
        width: 'auto',
        minWidth: '50px',
        maxWidth: '80px',
        maxHeight: '60px',
        fontSize: '1.2rem',
        textAlign: 'center',
        borderRadius: '8px',
        border: 'none',
        outline: 'none',
        fontWeight: 'bold',
    },
    groupFields: {
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: '5px',
        flexGrow: 1,
        minHeight: 0
    },
    fieldBox: {
        border: 'none',
        borderRadius: '10px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '0px 2px',
        backgroundColor: 'rgba(0,0,0,0.1)',
        overflow: 'hidden',
        minWidth: '60px',
        flexBasis: '0',
        flexGrow: 1,
        minHeight: '25px',
        maxHeight: '60px'
    },
    emptyGroup: {
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: 0.5,
        fontStyle: 'italic'
    },
    moduleGrid: {
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap: '10px',
        overflowY: 'auto',
        flex: 1,
        padding: '5px',
        minHeight: 0
    },
    moduleBtn: {
        padding: '15px 10px',
        borderRadius: '16px',
        border: 'none',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '10px',
        cursor: 'pointer',
        transition: 'transform 0.1s'
    }
};
