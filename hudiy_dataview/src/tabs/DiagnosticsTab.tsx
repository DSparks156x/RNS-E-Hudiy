import { useState, useEffect } from 'react';
import { useSocket } from '../hooks/useSocket';
import { useHudiyTheme } from '../hooks/useHudiyTheme';

interface DTC {
    code: string;
    code_dec: number;
    status: number;
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

export function DiagnosticsTab() {
    const theme = useHudiyTheme();
    // Use the socket hook to get the connection. We don't subscribe to fixed groups here.
    const { socket } = useSocket('diagnostics');

    const [selectedModule, setSelectedModule] = useState<number | null>(null);
    const [selectorOpen, setSelectorOpen] = useState(false);
    const [dtcs, setDtcs] = useState<DTC[]>([]);
    const [loadingDTCs, setLoadingDTCs] = useState(false);

    // Group Subscriptions
    const [group1, setGroup1] = useState<string>('');
    const [group2, setGroup2] = useState<string>('');
    const [group3, setGroup3] = useState<string>('');
    const [groupData, setGroupData] = useState<Record<string, any>>({});

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

    // Unsubscribe from old groups when module changes
    useEffect(() => {
        return () => {
            // We should tell server to drop old subs, but it handles cleanup via the heartbeat? No, toggle_action is explicit.
            // It's probably better to emit remove commands if we change modules.
        };
    }, [selectedModule]);

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

    const handleGroup1Change = (e: React.ChangeEvent<HTMLInputElement>) => {
        const val = e.target.value;
        toggleSubscription(group1, val);
        setGroup1(val);
    };

    const handleGroup2Change = (e: React.ChangeEvent<HTMLInputElement>) => {
        const val = e.target.value;
        toggleSubscription(group2, val);
        setGroup2(val);
    };

    const handleGroup3Change = (e: React.ChangeEvent<HTMLInputElement>) => {
        const val = e.target.value;
        toggleSubscription(group3, val);
        setGroup3(val);
    };

    const ModuleSelectorModal = () => (
        <div style={styles.modalOverlay} onClick={() => setSelectorOpen(false)}>
            <div style={{ ...styles.modalContent, backgroundColor: theme.surfaceColor }} onClick={(e) => e.stopPropagation()}>
                <h2 style={{ color: theme.onSurface }}>Select Module</h2>
                <div style={styles.moduleGrid}>
                    {KNOWN_MODULES.map(mod => (
                        <button
                            key={mod.id}
                            style={{ ...styles.moduleBtn, backgroundColor: theme.primary, color: theme.onSurface }}
                            onClick={() => {
                                setSelectedModule(mod.id);
                                setSelectorOpen(false);
                                setGroup1(''); setGroup2(''); setGroup3('');
                                setGroupData({});
                                setDtcs([]);
                            }}
                        >
                            <span style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>0x{mod.id.toString(16).padStart(2, '0').toUpperCase()}</span>
                            <span>{mod.name}</span>
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );

    const renderGroupFields = (grpId: string, values: any[]) => {
        if (!values || values.length === 0) return <div style={styles.emptyGroup}>No Data</div>;
        return (
            <div style={styles.groupFields}>
                {values.map((v, i) => (
                    <div key={i} style={{ ...styles.fieldBox, borderColor: theme.surfaceHighlight }}>
                        <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{v.value}</div>
                        <div style={{ fontSize: '0.8rem', color: theme.onSurfaceSecondary }}>{v.unit || '-'}</div>
                    </div>
                ))}
            </div>
        );
    };

    return (
        <div style={{ padding: '10px', height: '100%', display: 'flex', flexDirection: 'column', color: theme.onSurface }}>
            {/* Header / Module Selection */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
                <button
                    style={{ ...styles.mainSelectBtn, backgroundColor: theme.surfaceHighlight }}
                    onClick={() => setSelectorOpen(true)}
                >
                    {selectedModule !== null
                        ? `Module 0x${selectedModule.toString(16).padStart(2, '0').toUpperCase()}`
                        : 'Tap to Select Module'}
                </button>

                <button
                    style={{ ...styles.actionBtn, backgroundColor: selectedModule !== null ? theme.primary : '#555' }}
                    onClick={requestDTCs}
                    disabled={selectedModule === null || loadingDTCs}
                >
                    {loadingDTCs ? 'Reading...' : 'Read DTCs'}
                </button>
            </div>

            {/* Content Area split into DTCs and Measuring Groups */}
            <div style={{ display: 'flex', flex: 1, gap: '15px', overflow: 'hidden' }}>

                {/* Left Side: DTCs */}
                <div style={{ ...styles.panel, backgroundColor: theme.surfaceColor, flex: 1 }}>
                    <h3 style={{ marginTop: 0, borderBottom: `1px solid ${theme.surfaceHighlight}`, paddingBottom: '8px' }}>Fault Codes</h3>
                    <div style={{ overflowY: 'auto', flex: 1 }}>
                        {dtcs.length === 0 && !loadingDTCs && <div style={{ padding: '10px', opacity: 0.7 }}>No fault codes found.</div>}
                        {loadingDTCs && <div style={{ padding: '10px', opacity: 0.7 }}>Querying module...</div>}
                        {dtcs.map((dtc, i) => (
                            <div key={i} style={{ padding: '10px', borderBottom: `1px solid ${theme.surfaceHighlight}`, display: 'flex', justifyContent: 'space-between' }}>
                                <span style={{ fontFamily: 'monospace', fontSize: '1.2rem', fontWeight: 'bold' }}>{dtc.code}</span>
                                <span style={{ fontSize: '0.9rem', opacity: 0.7 }}>Status: 0x{dtc.status.toString(16).padStart(2, '0')}</span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Right Side: RT Data */}
                <div style={{ ...styles.panel, backgroundColor: theme.surfaceColor, flex: 1 }}>
                    <h3 style={{ marginTop: 0, borderBottom: `1px solid ${theme.surfaceHighlight}`, paddingBottom: '8px' }}>Measuring Groups</h3>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', flex: 1, overflowY: 'auto' }}>
                        {/* Group 1 */}
                        <div style={styles.groupRow}>
                            <input
                                type="number"
                                placeholder="Grp 1"
                                value={group1}
                                onChange={handleGroup1Change}
                                style={{ ...styles.groupInput, backgroundColor: theme.surfaceHighlight, color: theme.onSurface }}
                            />
                            <div style={{ flex: 1 }}>{renderGroupFields(group1, groupData[group1])}</div>
                        </div>

                        {/* Group 2 */}
                        <div style={styles.groupRow}>
                            <input
                                type="number"
                                placeholder="Grp 2"
                                value={group2}
                                onChange={handleGroup2Change}
                                style={{ ...styles.groupInput, backgroundColor: theme.surfaceHighlight, color: theme.onSurface }}
                            />
                            <div style={{ flex: 1 }}>{renderGroupFields(group2, groupData[group2])}</div>
                        </div>

                        {/* Group 3 */}
                        <div style={styles.groupRow}>
                            <input
                                type="number"
                                placeholder="Grp 3"
                                value={group3}
                                onChange={handleGroup3Change}
                                style={{ ...styles.groupInput, backgroundColor: theme.surfaceHighlight, color: theme.onSurface }}
                            />
                            <div style={{ flex: 1 }}>{renderGroupFields(group3, groupData[group3])}</div>
                        </div>
                    </div>
                </div>
            </div>

            {selectorOpen && <ModuleSelectorModal />}
        </div>
    );
}

const styles: Record<string, React.CSSProperties> = {
    mainSelectBtn: {
        padding: '15px 25px',
        fontSize: '1.5rem',
        borderRadius: '8px',
        border: 'none',
        color: 'white',
        cursor: 'pointer',
        boxShadow: '0 4px 6px rgba(0,0,0,0.3)',
        fontWeight: 'bold'
    },
    actionBtn: {
        padding: '15px 25px',
        fontSize: '1.3rem',
        borderRadius: '8px',
        border: 'none',
        color: 'white',
        cursor: 'pointer',
        fontWeight: 'bold',
        minWidth: '150px'
    },
    panel: {
        borderRadius: '8px',
        padding: '15px',
        display: 'flex',
        flexDirection: 'column',
    },
    groupRow: {
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        minHeight: '80px',
    },
    groupInput: {
        width: '60px',
        height: '60px',
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
        height: '100%',
    },
    fieldBox: {
        border: '1px solid',
        borderRadius: '6px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '5px',
        backgroundColor: 'rgba(0,0,0,0.1)'
    },
    emptyGroup: {
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: 0.5,
        fontStyle: 'italic'
    },
    modalOverlay: {
        position: 'fixed',
        top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000
    },
    modalContent: {
        width: '90%',
        maxHeight: '90%',
        borderRadius: '12px',
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
    },
    moduleGrid: {
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
        gap: '15px',
        overflowY: 'auto',
        marginTop: '15px'
    },
    moduleBtn: {
        padding: '15px',
        borderRadius: '8px',
        border: 'none',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '5px',
        cursor: 'pointer',
        boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
    }
};
