import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Socket } from 'socket.io-client';

interface TuneFile {
    name: string;
    artifact_id: string;
    size_bytes: number;
    type: string;
    modified: string;
}

interface EcuFlashInfo {
    connected: boolean;
    in_bootloader: boolean;
    part_number?: string | null;
    sw_version?: string | null;
    flash_counter?: number | null;
    flash_attempts?: number | null;
    last_flash_date?: string | null;
    flash_date?: string | null;
    last_tool_id?: number | null;
    system_desc?: string | null;
    error?: string;
}

interface FlashProgress {
    stage: string;
    percent: number;
    detail: string;
    speed: number;
    eta_sec?: number;
}

interface HaldexFlashModalProps {
    socket: Socket | null;
    theme: Record<string, string>;
    onClose: () => void;
    initialModule?: 'haldex-gen4' | 'pq-eps';
}

export function HaldexFlashModal({ socket, theme, onClose, initialModule = 'haldex-gen4' }: HaldexFlashModalProps) {
    const [module, setModule] = useState<'haldex-gen4' | 'pq-eps'>(initialModule);
    const [tunes, setTunes] = useState<TuneFile[]>([]);
    const [selectedTune, setSelectedTune] = useState<string>('');
    const [ecuInfo, setEcuInfo] = useState<EcuFlashInfo | null>(null);
    const [loadingInfo, setLoadingInfo] = useState(false);
    const [loadingTunes, setLoadingTunes] = useState(false);

    // Flash Execution State
    const [isFlashing, setIsFlashing] = useState(false);
    const [isReadout, setIsReadout] = useState(false);
    const [progress, setProgress] = useState<FlashProgress>({
        stage: 'IDLE',
        percent: 0,
        detail: '',
        speed: 0,
        eta_sec: 0
    });
    const [flashResult, setFlashResult] = useState<{ success: boolean; message: string; offline?: boolean; readout?: boolean } | null>(null);
    const [readout, setReadout] = useState<{ filename?: string; download_url?: string; report_url?: string } | null>(null);
    const [cancelRequested, setCancelRequested] = useState(false);
    const [cancelArmed, setCancelArmed] = useState(false);
    const [recoveryRequired, setRecoveryRequired] = useState(false);
    const [sectorRange, setSectorRange] = useState(
        initialModule === 'pq-eps' ? '385024:389119' : '98304:327679');
    const sectorChosen = useRef(false);

    // Hold-to-flash button state
    const [holdProgress, setHoldProgress] = useState(0);
    const holdTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const holdStartRef = useRef<number>(0);
    const cancelArmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Fetch tune list on mount
    useEffect(() => {
        if (!socket) return;

        setLoadingTunes(true);
        socket.emit('get_tunes_list', { module });

        const onTunesList = (data: TuneFile[]) => {
            setTunes(data || []);
            setLoadingTunes(false);
            if (module === 'pq-eps' && data?.[0]?.size_bytes === 4096) {
                sectorChosen.current = true;
                setSectorRange('385024:389119');
            }
            setSelectedTune(previous => data?.some(t => t.artifact_id === previous)
                ? previous : (data?.[0]?.artifact_id || ''));
        };

        const onEcuInfo = (info: EcuFlashInfo) => {
            setEcuInfo(info);
            setLoadingInfo(false);
            if (module === 'pq-eps' && !sectorChosen.current) {
                const revision = Number(info.sw_version?.trim());
                setSectorRange(info.connected && Number.isInteger(revision) && revision >= 3000
                    ? '385024:389119' : '40960:393215');
            } else if (!sectorChosen.current) {
                setSectorRange(info.connected && !info.in_bootloader && info.sw_version?.trim()
                    && info.sw_version.trim() !== '3016' ? '196608:262143' : '98304:327679');
            }
        };

        const onFlashProgress = (prog: FlashProgress) => {
            setIsFlashing(true);
            setFlashResult(null);
            setReadout(null);
            setProgress(prog);
        };
        const onOperationStarted = (detail: string) => {
            if (holdTimerRef.current) {
                clearInterval(holdTimerRef.current);
                holdTimerRef.current = null;
            }
            setHoldProgress(0);
            setIsFlashing(true);
            setCancelRequested(false);
            setCancelArmed(false);
            setFlashResult(null);
            setReadout(null);
            setProgress({ stage: 'STARTING', percent: 0, detail, speed: 0, eta_sec: 0 });
        };
        const onFlashStarted = () => {
            setIsReadout(false);
            onOperationStarted('Preparing to flash...');
        };
        const onReadoutStarted = () => {
            setIsReadout(true);
            onOperationStarted('Preparing Controller firmware readout...');
        };

        const onFlashComplete = (res: any) => {
            setIsFlashing(false);
            setIsReadout(false);
            setCancelRequested(false);
            setCancelArmed(false);
            const offline = res.dry_run === true || res.status === 'dry_run';
            const verified = res.boot_verified === true && res.checksum_verified === true
                && res.commit_outcome === 'acknowledged';
            setRecoveryRequired(previous => offline ? previous : Boolean(res.recovery_required) || !verified);
            setFlashResult({
                success: !res.recovery_required && (offline || verified),
                offline,
                message: offline ? 'No flash was performed.'
                    : verified ? 'Application boot verified after transfer and commit.'
                    : 'Flash incomplete; application boot is not verified. Select firmware and flash again.'
            });
        };

        const onFlashError = (err: any) => {
            // A rejected second request must not mark a running operation stopped.
            if (err.stopped !== false) setIsFlashing(false);
            if (err.stopped !== false) setIsReadout(false);
            setCancelRequested(false);
            setCancelArmed(false);
            setRecoveryRequired(previous => previous || Boolean(err.recovery_required));
            setFlashResult({
                success: false,
                message: `${err.message || 'Operation failed.'}${err.recovery_required ? ' Controller remains in bootloader; select firmware and flash again. Normal traffic remains paused.' : ''}`
            });
        };
        const onReadoutComplete = (res: any) => {
            setIsFlashing(false);
            setIsReadout(false);
            setCancelRequested(false);
            setCancelArmed(false);
            const success = res.status === 'ok' && res.stopped === true && !res.recovery_required;
            setRecoveryRequired(previous => previous || Boolean(res.recovery_required));
            setReadout(success ? { filename: res.filename, download_url: res.download_url, report_url: res.report_url } : null);
            setFlashResult({ success, readout: true, message: success
                ? `Readout saved (${res.size.toLocaleString()} bytes). Selected sectors captured; unread addresses padded with FF. No firmware was written.`
                : 'Readout failed. No complete download is available.' });
            if (success) setProgress(previous => ({ ...previous, percent: 100 }));
        };
        const onReadoutError = (err: any) => {
            onFlashError(err);
            if (err.report_url) setReadout({ report_url: err.report_url });
        };
        const onFlashAborted = (res: any) => onFlashError({ ...res, message: res.message || 'Operation stopped after cancellation.' });
        const onCancelRequested = () => setCancelRequested(true);
        const onDisconnect = () => {
            setLoadingInfo(false);
            setLoadingTunes(false);
            setFlashResult({success: false, message: 'Connection lost. Operation status unknown; reconnect before taking action.'});
        };

        socket.on('tunes_list', onTunesList);
        socket.on('ecu_flash_info', onEcuInfo);
        socket.on('haldex_flash_progress', onFlashProgress);
        socket.on('haldex_flash_started', onFlashStarted);
        socket.on('haldex_readout_started', onReadoutStarted);
        socket.on('haldex_readout_progress', onFlashProgress);
        socket.on('haldex_readout_error', onReadoutError);
        socket.on('haldex_flash_complete', onFlashComplete);
        socket.on('haldex_readout_complete', onReadoutComplete);
        socket.on('haldex_flash_error', onFlashError);
        socket.on('haldex_flash_aborted', onFlashAborted);
        socket.on('haldex_flash_cancel_requested', onCancelRequested);
        socket.on('disconnect', onDisconnect);

        return () => {
            socket.off('tunes_list', onTunesList);
            socket.off('ecu_flash_info', onEcuInfo);
            socket.off('haldex_flash_progress', onFlashProgress);
            socket.off('haldex_flash_started', onFlashStarted);
            socket.off('haldex_readout_started', onReadoutStarted);
            socket.off('haldex_readout_progress', onFlashProgress);
            socket.off('haldex_readout_error', onReadoutError);
            socket.off('haldex_flash_complete', onFlashComplete);
            socket.off('haldex_readout_complete', onReadoutComplete);
            socket.off('haldex_flash_error', onFlashError);
            socket.off('haldex_flash_aborted', onFlashAborted);
            socket.off('haldex_flash_cancel_requested', onCancelRequested);
            socket.off('disconnect', onDisconnect);
            if (holdTimerRef.current) clearInterval(holdTimerRef.current);
            if (cancelArmTimerRef.current) clearTimeout(cancelArmTimerRef.current);
        };
    }, [socket, module]);

    const handleReadEcuInfo = () => {
        if (!socket || isFlashing || recoveryRequired) return;
        setLoadingInfo(true);
        socket.emit('get_ecu_flash_info', { module });
    };

    const handleRefreshTunes = () => {
        if (!socket || isFlashing) return;
        setLoadingTunes(true);
        socket.emit('get_tunes_list', { module });
    };

    const startHold = () => {
        if (isFlashing || loadingInfo || !selectedTune || holdTimerRef.current) return;
        if (module === 'pq-eps' && sectorRange !== '40960:393215') {
            const revision = Number(ecuInfo?.sw_version?.trim());
            if (!ecuInfo?.connected || !Number.isInteger(revision) || revision < 3000) return;
        }
        setFlashResult(null);
        holdStartRef.current = Date.now();
        setHoldProgress(0);

        holdTimerRef.current = setInterval(() => {
            const elapsed = Date.now() - holdStartRef.current;
            const pct = Math.min(100, (elapsed / 1200) * 100);
            setHoldProgress(pct);

            if (pct >= 100) {
                clearInterval(holdTimerRef.current!);
                holdTimerRef.current = null;
                executeFlash();
            }
        }, 25);
    };

    const stopHold = () => {
        if (holdTimerRef.current) {
            clearInterval(holdTimerRef.current);
            holdTimerRef.current = null;
        }
        setHoldProgress(0);
    };

    const executeFlash = () => {
        if (!socket || !selectedTune) return;
        setIsFlashing(true);
        setIsReadout(false);
        setFlashResult(null);
        setReadout(null);
        setProgress({
            stage: 'STARTING',
            percent: 1,
            detail: 'Preparing to flash...',
            speed: 0,
            eta_sec: 0
        });

        setCancelRequested(false);
        setCancelArmed(false);
        const [start_addr, end_addr] = sectorRange.split(':').map(Number);
        socket.emit('start_haldex_flash', { module, artifact_id: selectedTune, dry_run: false, start_addr, end_addr });
    };

    const executeReadout = () => {
        if (!socket?.connected || isFlashing || loadingInfo || holdTimerRef.current) return;
        setIsFlashing(true);
        setIsReadout(true);
        setFlashResult(null);
        setReadout(null);
        setCancelRequested(false);
        setCancelArmed(false);
        setProgress({ stage: 'STARTING', percent: 0, detail: 'Preparing Controller firmware readout...', speed: 0, eta_sec: 0 });
        const [start_addr, end_addr] = sectorRange.split(':').map(Number);
        socket.emit('start_haldex_readout', { module, start_addr, end_addr });
    };

    const handleCancel = () => {
        if (!socket || !isFlashing || cancelRequested) return;
        if (!cancelArmed) {
            setCancelArmed(true);
            if (cancelArmTimerRef.current) clearTimeout(cancelArmTimerRef.current);
            cancelArmTimerRef.current = setTimeout(() => {
                cancelArmTimerRef.current = null;
                setCancelArmed(false);
            }, 3000);
            return;
        }
        if (cancelArmTimerRef.current) clearTimeout(cancelArmTimerRef.current);
        cancelArmTimerRef.current = null;
        setCancelArmed(false);
        socket.emit('cancel_haldex_flash');
    };

    const selectedTuneObj = tunes.find(t => t.artifact_id === selectedTune);

    const content = (
        <div style={styles.overlay}>
            <div
                style={{
                    ...styles.modal,
                    backgroundColor: theme.surface || '#181818',
                    color: theme.onSurface || '#eee',
                    borderColor: theme.outline || '#444'
                }}
            >
                {/* Header */}
                <div style={styles.header}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                        <span style={{ fontWeight: 'bold', fontSize: '1rem', letterSpacing: '0.02em' }}>
                            Vehicle Module Flasher
                        </span>
                        <span style={{ fontSize: '0.8rem', opacity: 0.6, fontFamily: 'monospace' }}>
                            {module === 'pq-eps' ? 'Mod 0x09 (PQ EPS)' : 'Mod 0x0A (Haldex Gen4)'}
                        </span>
                        {!isFlashing && <select
                            aria-label="Controller module"
                            value={module}
                            onChange={event => {
                                const next = event.target.value as 'haldex-gen4' | 'pq-eps';
                                setModule(next);
                                setEcuInfo(null);
                                setSelectedTune('');
                                setFlashResult(null);
                                setReadout(null);
                                sectorChosen.current = false;
                                setSectorRange(next === 'pq-eps' ? '385024:389119' : '98304:327679');
                            }}
                            style={{ ...styles.select, width: '145px', padding: '4px 6px', backgroundColor: theme.surfaceVariant || '#252525', color: theme.onSurface || '#eee' }}
                        >
                            <option value="haldex-gen4">Haldex Gen4</option>
                            <option value="pq-eps">PQ EPS</option>
                        </select>}
                    </div>

                    {!isFlashing && (
                        <button
                            onClick={onClose}
                            style={{
                                ...styles.closeBtn,
                                backgroundColor: theme.surfaceDim || 'rgba(255,255,255,0.08)',
                                color: theme.onSurface || '#fff'
                            }}
                        >
                            Back
                        </button>
                    )}
                </div>

                {/* Body: 2-Column Compact Grid for 800x400 display */}
                <div style={styles.body}>
                    {/* Left Column: Controller Status & Sector Range */}
                    <div style={styles.col}>
                        <div style={styles.sectionHeader}>
                            <span>Controller Status</span>
                            <button
                                onClick={handleReadEcuInfo}
                                disabled={loadingInfo || isFlashing || recoveryRequired}
                                style={{ ...styles.subBtn, backgroundColor: theme.primaryContainer || '#2c3e50', color: theme.onPrimaryContainer || '#fff' }}
                            >
                                {loadingInfo ? 'Reading...' : 'Query Controller'}
                            </button>
                        </div>

                        <div style={styles.infoTable}>
                            <div style={styles.tableRow}>
                                <span style={styles.cellLabel}>Part Number</span>
                                <span style={styles.cellValue}>{ecuInfo?.part_number || '—'}</span>
                            </div>
                            <div style={styles.tableRow}>
                                <span style={styles.cellLabel}>Software Rev</span>
                                <span style={styles.cellValue}>{ecuInfo?.sw_version || '—'}</span>
                            </div>
                            <div style={styles.tableRow}>
                                <span style={styles.cellLabel}>Flash Cycles</span>
                                <span style={styles.cellValue}>
                                    {ecuInfo?.flash_counter !== null && ecuInfo?.flash_counter !== undefined
                                        ? `${ecuInfo.flash_counter} ok / ${ecuInfo.flash_attempts || 0} tries`
                                        : '—'}
                                </span>
                            </div>
                            <div style={styles.tableRow}>
                                <span style={styles.cellLabel}>Last Flash Date</span>
                                <span style={styles.cellValue}>{ecuInfo?.last_flash_date || ecuInfo?.flash_date || '—'}</span>
                            </div>
                            <div style={styles.tableRow}>
                                <span style={styles.cellLabel}>Active State</span>
                                <span style={{ ...styles.cellValue, color: ecuInfo?.in_bootloader ? '#ffb74d' : '#81c784' }}>
                                    {ecuInfo ? (ecuInfo.in_bootloader ? 'Bootloader' : 'Application') : '—'}
                                </span>
                            </div>
                        </div>

                        <label style={styles.checkLabel}>{module === 'pq-eps' ? 'Flash region' : 'Sectors'}</label>
                        <select value={sectorRange} disabled={isFlashing}
                            onChange={e => { sectorChosen.current = true; setSectorRange(e.target.value); }}
                            style={{ ...styles.select, backgroundColor: theme.surfaceVariant || '#252525', color: theme.onSurface || '#eee' }}>
                            {module === 'pq-eps' ? <>
                                <option value="40960:393215">Full firmware — 0x0A000–0x5FFFF</option>
                                <option value="380928:385023">Configuration — block 0x5D</option>
                                <option value="385024:389119">Steer dataset — block 0x5E</option>
                            </> : <>
                                <option value="196608:262143">Calibration — sector 6</option>
                                <option value="98304:327679">Full application — sectors 4–7</option>
                                <option value="98304:131071">Sector 4</option>
                                <option value="131072:196607">Sector 5</option>
                                <option value="262144:327679">Sector 7</option>
                                <option value="98304:196607">Sectors 4–5</option>
                                <option value="98304:262143">Sectors 4–6</option>
                                <option value="131072:262143">Sectors 5–6</option>
                                <option value="131072:327679">Sectors 5–7</option>
                                <option value="196608:327679">Sectors 6–7</option>
                            </>}
                        </select>
                        <div style={{ fontSize: '0.75rem', lineHeight: 1.4 }}>
                            {module === 'pq-eps'
                                ? 'Block 0x5E is the default. Partial-region flash is approved only after the live rack reports software revision 3000 or newer; older or unknown revisions require full 0x0A000–0x5FFFF. Standalone 4 KiB files remain limited to 0x5E and must pass CRC-16/XMODEM validation. EPS readout is experimental.'
                                : '320 KiB images are automatically patched and checksums repaired. Query Controller to choose the default: Calibration for non-3016 application firmware; Full for 3016 or unknown. Flash and readout use the selected sectors.'}
                        </div>
                        {ecuInfo?.error && <div role="alert">{ecuInfo.error}</div>}
                        {recoveryRequired && <div role="alert" style={{ color: '#ffb74d' }}>
                            Flash incomplete; Controller remains in bootloader. Select firmware and hold to flash again.
                            Normal traffic stays paused until application boot is verified.
                        </div>}

                    </div>

                    {/* Right Column: Tune Selector, Progress, Actions */}
                    <div style={styles.col}>
                        <div style={styles.sectionHeader}>
                            <span>Firmware</span>
                            <button
                                onClick={handleRefreshTunes}
                                disabled={loadingTunes || isFlashing}
                                style={{ ...styles.subBtn, backgroundColor: theme.surfaceDim || '#2c3e50', color: theme.onSurface || '#fff' }}
                            >
                                {loadingTunes ? '...' : 'Refresh'}
                            </button>
                        </div>

                        <select
                            value={selectedTune}
                            onChange={(e) => {
                                setSelectedTune(e.target.value);
                                const selected = tunes.find(t => t.artifact_id === e.target.value);
                                if (module === 'pq-eps' && selected?.size_bytes === 4096) {
                                    sectorChosen.current = true;
                                    setSectorRange('385024:389119');
                                }
                            }}
                            disabled={isFlashing}
                            style={{
                                ...styles.select,
                                backgroundColor: theme.surfaceVariant || '#252525',
                                color: theme.onSurface || '#eee',
                                borderColor: theme.outlineVariant || '#444',
                                colorScheme: 'dark'
                            }}
                        >
                            {tunes.length === 0 ? (
                                <option value="" style={styles.option}>No firmware files available</option>
                            ) : (
                                tunes.map((t) => (
                                    <option key={t.artifact_id} value={t.artifact_id} style={styles.option}>
                                        {t.name} ({Math.round(t.size_bytes / 1024)}K)
                                    </option>
                                ))
                            )}
                        </select>

                        {selectedTuneObj && (
                            <div style={styles.fileDetail}>
                                <span>{selectedTuneObj.type}</span>
                                <span>{selectedTuneObj.size_bytes} B</span>
                                <span>{selectedTuneObj.modified}</span>
                            </div>
                        )}

                        {/* Flash Progress & Output */}
                        <div style={styles.progressBox}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ fontWeight: 'bold', fontSize: '0.85rem', color: theme.primary || '#90caf9' }}>
                                    {isFlashing ? progress.stage : (flashResult ? (flashResult.success ? (flashResult.readout ? 'Readout complete' : flashResult.offline ? 'No flash performed' : 'Boot verified') : 'Attention required') : 'Ready')}
                                </span>
                                <span style={{ fontFamily: 'monospace', fontSize: '0.9rem', fontWeight: 'bold' }}>
                                    {isFlashing ? `${progress.percent.toFixed(1)}%` : ''}
                                </span>
                            </div>

                            <div style={styles.progressBarTrack}>
                                <div
                                    style={{
                                        ...styles.progressBarFill,
                                        width: `${progress.percent}%`,
                                        backgroundColor: flashResult && !flashResult.success ? '#e53935' : (theme.primary || '#388e3c')
                                    }}
                                />
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', opacity: 0.8, marginTop: '3px' }}>
                                <span style={{ overflowWrap: 'anywhere' }}>
                                    {flashResult ? flashResult.message : (progress.detail || 'Ready to flash or read selected sectors')}
                                </span>
                                {isFlashing && (progress.eta_sec ?? 0) > 0 && (
                                    <span style={{ fontFamily: 'monospace' }}>
                                        ETA: {Math.round(progress.eta_sec!)}s
                                    </span>
                                )}
                            </div>
                            {readout && <div style={{ fontSize: '0.75rem', overflowWrap: 'anywhere' }}>
                                {readout.download_url && <a href={readout.download_url} download={readout.filename} style={{ color: theme.primary || '#90caf9' }}>
                                    Download {readout.filename}
                                </a>}
                                {readout.report_url && <div><a href={readout.report_url} download style={{ color: theme.primary || '#90caf9' }}>Download readout report</a></div>}
                            </div>}
                        </div>

                        {/* Action Buttons */}
                        <div style={styles.actionRow}>
                            {!isFlashing && <button
                                onClick={executeReadout}
                                disabled={loadingInfo || holdProgress > 0 || !socket?.connected}
                                style={{ ...styles.btn, backgroundColor: theme.primaryContainer || '#2c3e50', color: theme.onPrimaryContainer || '#fff', width: '100%', marginBottom: '6px' }}
                            >{module === 'pq-eps' ? 'Try EPS firmware readout' : 'Read Controller firmware'}</button>}
                            {isFlashing && isReadout ? (
                                <button
                                    key="cancel-readout"
                                    onClick={handleCancel}
                                    disabled={cancelRequested}
                                    style={{ ...styles.btn, backgroundColor: '#c62828', color: '#fff', width: '100%' }}
                                >
                                    {cancelRequested ? 'Cancellation requested — waiting'
                                        : cancelArmed ? 'Tap again to confirm cancellation' : 'Cancel readout'}
                                </button>
                            ) : isFlashing ? (
                                <div role="status" style={{ ...styles.btn, backgroundColor: '#6d1b1b', color: '#fff', width: '100%', textAlign: 'center' }}>
                                    Flash in progress — do not power off
                                </div>
                            ) : (
                                <button
                                    key="start-flash"
                                    onMouseDown={startHold}
                                    onMouseUp={stopHold}
                                    onMouseLeave={stopHold}
                                    onTouchStart={startHold}
                                    onTouchEnd={stopHold}
                                    disabled={!selectedTune || loadingInfo || !socket?.connected || (module === 'pq-eps' && sectorRange !== '40960:393215' && (!ecuInfo?.connected || !Number.isInteger(Number(ecuInfo.sw_version?.trim())) || Number(ecuInfo.sw_version?.trim()) < 3000))}
                                    style={{
                                        ...styles.btn,
                                        ...styles.holdBtn,
                                        backgroundColor: !selectedTune || (module === 'pq-eps' && sectorRange !== '40960:393215' && (!ecuInfo?.connected || !Number.isInteger(Number(ecuInfo.sw_version?.trim())) || Number(ecuInfo.sw_version?.trim()) < 3000)) ? '#444' : '#d32f2f',
                                        color: '#fff',
                                        cursor: !selectedTune || (module === 'pq-eps' && sectorRange !== '40960:393215' && (!ecuInfo?.connected || !Number.isInteger(Number(ecuInfo.sw_version?.trim())) || Number(ecuInfo.sw_version?.trim()) < 3000)) ? 'not-allowed' : 'pointer',
                                        width: '100%'
                                    }}
                                >
                                    <div
                                        style={{
                                            ...styles.holdFill,
                                            width: `${holdProgress}%`,
                                            backgroundColor: 'rgba(255, 255, 255, 0.35)'
                                        }}
                                    />
                                    <span style={{ position: 'relative', zIndex: 2 }}>
                                        {holdProgress > 0 ? `Hold to Confirm (${Math.round(holdProgress)}%)`
                                            : module === 'pq-eps' && sectorRange !== '40960:393215' && (!ecuInfo?.connected || !Number.isInteger(Number(ecuInfo.sw_version?.trim())) || Number(ecuInfo.sw_version?.trim()) < 3000)
                                                ? 'Query revision 3000+ or select Full' : 'Hold to Flash'}
                                    </span>
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );

    // Use React Portal to attach to document.body outside CSS-transformed tab strip
    return createPortal(content, document.body);
}

const styles: Record<string, React.CSSProperties> = {
    overlay: {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        backgroundColor: 'rgba(0, 0, 0, 0.82)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 99999,
        padding: '8px',
        boxSizing: 'border-box',
    },
    modal: {
        width: '760px',
        maxWidth: '96vw',
        height: '370px',
        maxHeight: '94vh',
        borderRadius: '10px',
        border: '1px solid #444',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.8)',
        boxSizing: 'border-box',
        overflow: 'hidden',
    },
    header: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '6px 14px',
        borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
        flexShrink: 0,
    },
    closeBtn: {
        padding: '4px 12px',
        border: 'none',
        borderRadius: '5px',
        cursor: 'pointer',
        fontSize: '0.85rem',
        fontWeight: 'bold',
    },
    body: {
        padding: '10px 14px',
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '14px',
        flexGrow: 1,
        overflow: 'auto',
    },
    col: {
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        minHeight: 0,
    },
    sectionHeader: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: '0.85rem',
        fontWeight: 'bold',
        opacity: 0.9,
    },
    subBtn: {
        padding: '3px 8px',
        fontSize: '0.75rem',
        borderRadius: '4px',
        border: 'none',
        cursor: 'pointer',
        fontWeight: 'bold',
    },
    infoTable: {
        display: 'flex',
        flexDirection: 'column',
        gap: '3px',
        backgroundColor: 'rgba(255, 255, 255, 0.04)',
        padding: '6px 10px',
        borderRadius: '6px',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        fontSize: '0.8rem',
    },
    tableRow: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
    },
    cellLabel: {
        opacity: 0.65,
    },
    cellValue: {
        fontFamily: 'monospace',
        fontWeight: 'bold',
    },
    fieldLabel: {
        fontSize: '0.75rem',
        opacity: 0.7,
        marginBottom: '2px',
    },
    select: {
        width: '100%',
        padding: '6px 8px',
        borderRadius: '5px',
        fontSize: '0.82rem',
        backgroundColor: '#222222',
        color: '#eeeeee',
        border: '1px solid #444444',
        outline: 'none',
        boxSizing: 'border-box',
        colorScheme: 'dark',
    },
    option: {
        backgroundColor: '#222222',
        color: '#eeeeee',
    },
    checkboxRow: {
        display: 'flex',
        gap: '16px',
        marginTop: '4px',
        fontSize: '0.8rem',
    },
    checkLabel: {
        display: 'flex',
        alignItems: 'center',
        gap: '5px',
        cursor: 'pointer',
    },
    fileDetail: {
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: '0.75rem',
        opacity: 0.7,
        padding: '0 2px',
    },
    progressBox: {
        backgroundColor: 'rgba(0, 0, 0, 0.35)',
        borderRadius: '6px',
        padding: '8px 10px',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        marginTop: 'auto',
    },
    progressBarTrack: {
        width: '100%',
        height: '10px',
        backgroundColor: 'rgba(255, 255, 255, 0.1)',
        borderRadius: '5px',
        overflow: 'hidden',
    },
    progressBarFill: {
        height: '100%',
        borderRadius: '5px',
        transition: 'width 0.1s linear',
    },
    actionRow: {
        marginTop: '6px',
    },
    btn: {
        padding: '8px 14px',
        borderRadius: '6px',
        border: 'none',
        fontWeight: 'bold',
        fontSize: '0.9rem',
        cursor: 'pointer',
    },
    holdBtn: {
        position: 'relative',
        userSelect: 'none',
        overflow: 'hidden',
    },
    holdFill: {
        position: 'absolute',
        top: 0,
        left: 0,
        bottom: 0,
        transition: 'width 0.025s linear',
    },
};
