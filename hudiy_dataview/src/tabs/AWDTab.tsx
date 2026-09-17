import { useState } from 'react';
import { Socket } from 'socket.io-client';
import { Gauge } from '../components/Gauge';
import { LiveText } from '../components/LiveText';
import { useHaldexAndLogger } from '../hooks/useHaldexAndLogger';

const fmtVal = (val: number | string, unit: string = '') => {
  const v = typeof val === 'number' ? val : parseFloat(val);
  return isNaN(v) ? '--' : `${v.toFixed(1)} ${unit}`;
};

const formatSeconds = (sec: number) => {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
};

interface AWDTabProps {
  socket?: Socket | null;
}

export function AWDTab({ socket = null }: AWDTabProps) {
  const [loggerProfile, setLoggerProfile] = useState('haldex');
  const {
    haldex,
    logger,
    setMode,
    startLogging,
    stopLogging,
    addMarker
  } = useHaldexAndLogger(socket);

  return (
    <section id="awd" className="tab-content active">
      <div className="awd-layout">
        {/* Column 1: Performance Gauges */}
        <div className="panel awd-main">
          <h3>Haldex Engagement</h3>
          <div className="gauges-row">
            <div className="gauge-wrapper">
              <Gauge id="gauge_awd_pres" groupKey="10:3" index={0} min={0} max={60} label={['Bar', 'Oil Pressure']} sizeClass="gauge-md" />
            </div>
            <div className="gauge-wrapper">
              <Gauge id="gauge_awd_torque" groupKey="10:3" index={1} min={0} max={2000} label={['Nm', 'Est. Torque']} sizeClass="gauge-md" />
            </div>
          </div>
          <div className="extra-vals-grid">
            <div className="col">
              <div className="val-row-sm">
                <span className="label">Valve (N273):</span>
                <span><LiveText groupKey="10:3" index={2} format={(v) => fmtVal(v, '%')} /></span>
              </div>
            </div>
            <div className="col">
              <div className="val-row-sm">
                <span className="label">Current:</span>
                <span><LiveText groupKey="10:3" index={3} format={(v) => fmtVal(v, 'mA')} /></span>
              </div>
            </div>
          </div>
        </div>

        {/* Column 2: Haldex Tuning Mode & Logger Control */}
        <div className="awd-center-col">
          {/* Haldex Mode Switcher Card */}
          <div className="haldex-panel">
            <div className="haldex-header">
              <h3>Haldex Tuning</h3>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                {haldex.token_ok && (
                  <span className="haldex-badge synced" title="Safety Token Valid: Brake policy armed">
                    ARMED
                  </span>
                )}
                <span className={`haldex-badge ${haldex.status}`}>
                  {haldex.status}
                </span>
              </div>
            </div>

            {/* Mode Segmented Selector */}
            <div className="mode-selector">
              <button
                className={`mode-btn${haldex.desired_mode === 0 ? ' active' : ''}`}
                onClick={() => setMode(0)}
              >
                Stock
              </button>
              <button
                className={`mode-btn${haldex.desired_mode === 1 ? ' active' : ''}`}
                onClick={() => setMode(1)}
              >
                Perf
              </button>
              <button
                className={`mode-btn${haldex.desired_mode === 2 ? ' active' : ''}`}
                onClick={() => setMode(2)}
              >
                Comp
              </button>
            </div>

            {/* Real-time Uncensored Signals */}
            <div className="haldex-metrics-row">
              <div className="haldex-metric">
                <span className="lbl">Cmd Torque</span>
                <span className="val">{haldex.b08_torque_nm.toFixed(1)} <small>Nm</small></span>
              </div>
              <div className="haldex-metric">
                <span className="lbl">Slip Trq</span>
                <span className="val">{haldex.a7c_slip_nm.toFixed(1)} <small>Nm</small></span>
              </div>
              <div className="haldex-metric">
                <span className="lbl">Active</span>
                <span className="val" style={{ fontSize: '11px', color: 'var(--on-surface)' }}>
                  {haldex.active_name || '--'}
                </span>
              </div>
            </div>
          </div>

          {/* Drive Session Logger Card */}
          <div className="logger-panel">
            <div className="logger-header">
              <h3>Drive Logger <small>{logger.profile}</small></h3>
              <span className={`rec-badge ${logger.recording ? 'recording' : 'idle'}`}>
                <span className="rec-dot" />
                {logger.recording ? 'REC' : 'IDLE'}
              </span>
            </div>

            <div className="logger-controls">
              <select
                className="logger-profile-select"
                style={{
                  minWidth: '108px',
                  border: '1px solid var(--outline)',
                  borderRadius: '8px',
                  padding: '6px 8px',
                  background: 'var(--surface-dim)',
                  color: 'var(--on-surface)',
                }}
                value={loggerProfile}
                disabled={logger.recording}
                onChange={(event) => setLoggerProfile(event.target.value)}
                aria-label="Logging profile"
              >
                {(logger.available_profiles.length ? logger.available_profiles : [
                  { name: 'haldex', description: 'Fused Haldex logging' },
                ]).map((profile) => (
                  <option key={profile.name} value={profile.name} title={profile.description}>
                    {profile.name === 'haldex' ? 'Haldex fused' : 'Raw CAN'}
                  </option>
                ))}
              </select>
              {logger.recording ? (
                <button className="rec-btn stop" onClick={() => stopLogging()}>
                  Stop Recording
                </button>
              ) : (
                <button className="rec-btn start" onClick={() => startLogging(undefined, loggerProfile)}>
                  Start Logging
                </button>
              )}
            </div>

            {/* Quick Marker Buttons */}
            <div className="marker-grid">
              <button className="marker-btn" onClick={() => addMarker('DRIVER: Understeer')}>
                Understeer
              </button>
              <button className="marker-btn" onClick={() => addMarker('DRIVER: Oversteer')}>
                Oversteer
              </button>
              <button className="marker-btn" onClick={() => addMarker('DRIVER: Launch')}>
                Launch
              </button>
            </div>

            <div className="logger-stats-row">
              <span>Time: {formatSeconds(logger.uptime_sec)}</span>
              <span>Rows: {logger.rows_written.toLocaleString()}</span>
              <span>Marks: {logger.markers_logged}</span>
            </div>
          </div>
        </div>

        {/* Column 3: Status & Modes */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', height: '100%' }}>
          {/* Group 1: Status */}
          <div className="panel awd-status" style={{ flex: 1 }}>
            <h3>System Status</h3>
            <div className="val-list">
              <div className="val-row">
                <span className="label">Oil Temp</span>
                <span className="value"><LiveText groupKey="10:1" index={0} format={(v) => fmtVal(v, '°C')} /></span>
              </div>
              <div className="val-row">
                <span className="label">Plate Temp</span>
                <span className="value"><LiveText groupKey="10:1" index={1} format={(v) => fmtVal(v, '°C')} /></span>
              </div>
              <div className="val-row">
                <span className="label">Supply Volt</span>
                <span className="value"><LiveText groupKey="10:1" index={2} format={(v) => fmtVal(v, 'V')} /></span>
              </div>
            </div>
          </div>

          {/* Group 5: Modes */}
          <div className="panel awd-modes" style={{ flex: 1 }}>
            <h3>Modes</h3>
            <div className="val-list">
              <div className="val-row">
                <span className="label">CAN Out</span>
                <span className="value sm"><LiveText groupKey="10:5" index={0} /></span>
              </div>
              <div className="val-row">
                <span className="label">Veh Mode</span>
                <span className="value sm"><LiveText groupKey="10:5" index={1} /></span>
              </div>
              <div className="val-row">
                <span className="label">Slip Ctrl</span>
                <span className="value sm"><LiveText groupKey="10:5" index={2} /></span>
              </div>
              <div className="val-row">
                <span className="label">Op Mode</span>
                <span className="value sm"><LiveText groupKey="10:5" index={3} /></span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
