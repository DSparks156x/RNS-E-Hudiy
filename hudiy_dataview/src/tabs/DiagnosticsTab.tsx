import { useState, useEffect, useRef } from 'react';
import { useSocket } from '../hooks/useSocket';
import { useHudiyTheme } from '../hooks/useHudiyTheme';
import { Keypad } from '../components/Keypad';

interface DTC {
    code: string;
    code_dec: number;
    status: number;
    freeze_frame_raw?: string[];
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
                setDtcs(data.dtcs || []);
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
        socket.emit('request_dtcs', { module: selectedModule });
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
                {values.map((v, i) => (
                    <div key={i} style={{ ...styles.fieldBox, borderColor: 'rgba(255,255,255,0.1)' }}>
                        <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{v.value}</div>
                        <div style={{ fontSize: '0.8rem', color: '#aaa' }}>{v.unit || '-'}</div>
                    </div>
                ))}
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
                    style={{ ...styles.actionBtn, backgroundColor: 'rgba(0,0,0,0.3)', color: theme.onSurface, border: 'none' }}
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
                    }}
                >
                    ← Back
                </button>

                <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    <h2 style={{ margin: 0, opacity: 0.9 }}>
                        {KNOWN_MODULES.find(m => m.id === selectedModule)?.name || 'Unknown'}
                    </h2>
                    <span style={{ fontSize: '0.9rem', opacity: 0.7, marginTop: '2px' }}>
                        0x{selectedModule.toString(16).padStart(2, '0').toUpperCase()}
                    </span>
                </div>

                <button
                    style={{ ...styles.actionBtn, backgroundColor: loadingDTCs ? '#555' : theme.primary }}
                    onClick={requestDTCs}
                    disabled={loadingDTCs}
                >
                    {loadingDTCs ? 'Reading...' : 'Read DTCs'}
                </button>
            </div>

            {/* Content Area split into DTCs and Measuring Groups */}
            <div style={{ display: 'flex', flexGrow: 1, gap: '15px', minHeight: 0, height: '100%' }}>

                {/* Left Side: DTCs (and Keypad overlay) */}
                <div style={{ ...styles.panel, backgroundColor: 'rgba(0,0,0,0.3)', flexGrow: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%', boxSizing: 'border-box', position: 'relative' }}>
                    <h3 style={{ marginTop: 0, borderBottom: `1px solid rgba(255,255,255,0.1)`, paddingBottom: '8px', flexShrink: 0 }}>Fault Codes</h3>
                    <div style={{ overflowY: 'auto', flexGrow: 1, minHeight: 0 }}>
                        {dtcs.length === 0 && !loadingDTCs && <div style={{ padding: '10px', opacity: 0.7 }}>No fault codes found.</div>}
                        {loadingDTCs && <div style={{ padding: '10px', opacity: 0.7 }}>Querying module...</div>}
                        {dtcs.map((dtc, i) => (
                            <div key={i} style={{ padding: '10px', borderBottom: `1px solid rgba(255,255,255,0.1)`, display: 'flex', flexDirection: 'column' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                    <span style={{ fontFamily: 'monospace', fontSize: '1.2rem', fontWeight: 'bold' }}>{dtc.code}</span>
                                    <span style={{ fontSize: '0.9rem', opacity: 0.7 }}>Status: 0x{dtc.status.toString(16).padStart(2, '0')}</span>
                                </div>
                                {dtc.freeze_frame_raw && dtc.freeze_frame_raw.length > 0 && (
                                    <div style={{ marginTop: '8px', padding: '6px', backgroundColor: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                                        <span style={{ fontSize: '0.8rem', opacity: 0.6, display: 'block', marginBottom: '4px' }}>Freeze Frame (Raw Hex)</span>
                                        <span style={{ fontFamily: 'monospace', fontSize: '0.9rem', color: theme.primary, wordBreak: 'break-all' }}>
                                            {dtc.freeze_frame_raw.join(' ')}
                                        </span>
                                    </div>
                                )}
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
                <div style={{ ...styles.panel, backgroundColor: 'rgba(0,0,0,0.3)', flexGrow: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%', boxSizing: 'border-box' }}>
                    <h3 style={{ marginTop: 0, borderBottom: `1px solid rgba(255,255,255,0.1)`, paddingBottom: '8px', flexShrink: 0 }}>Measuring Groups</h3>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', flexGrow: 1, overflowY: 'auto', minHeight: 0, height: '100%', paddingRight: '5px' }}>
                        {/* Group 1 */}
                        <div style={styles.groupRow}>
                            <input
                                type="text"
                                readOnly
                                placeholder="Grp 1"
                                value={activeKeypad === 1 ? tempKeypadVal : group1}
                                onClick={() => handleInputClick(1, group1)}
                                style={{ ...styles.groupInput, backgroundColor: activeKeypad === 1 ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.1)', color: theme.onSurface, cursor: 'pointer' }}
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
                                style={{ ...styles.groupInput, backgroundColor: activeKeypad === 2 ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.1)', color: theme.onSurface, cursor: 'pointer' }}
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
                                style={{ ...styles.groupInput, backgroundColor: activeKeypad === 3 ? 'rgba(255,255,255,0.3)' : 'rgba(255,255,255,0.1)', color: theme.onSurface, cursor: 'pointer' }}
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
        borderRadius: '8px',
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
        padding: '5px',
        backgroundColor: 'rgba(0,0,0,0.1)',
        overflow: 'hidden',
        minWidth: 0,
        minHeight: 0
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
