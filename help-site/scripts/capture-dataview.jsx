// Capture-only fixture: actual DataView components, no socket or controller connection.
import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { EngineTab } from '../../hudiy_dataview/src/tabs/EngineTab';
import { TransmissionTab } from '../../hudiy_dataview/src/tabs/TransmissionTab';
import { AWDTab } from '../../hudiy_dataview/src/tabs/AWDTab';
import { DataLogsTab } from '../../hudiy_dataview/src/tabs/DataLogsTab';
import { DiagnosticsTab } from '../../hudiy_dataview/src/tabs/DiagnosticsTab';
import { DataStore } from '../../hudiy_dataview/src/store/DataStore';
import { fixtureSocket } from './capture-socket';
import { catalog, installDataLogsFixture } from './capture-data-logs';
import '../../hudiy_dataview/static/css/style_v3.css';

installDataLogsFixture();
const scene = new URLSearchParams(window.location.search).get('scene') || 'engine';
const safeDiagnostics = typeof __CAPTURE_SOCKET_FIXTURE__ !== 'undefined' && __CAPTURE_SOCKET_FIXTURE__;

const values = {
  'engine.maf': 128, 'engine.boost.actual_absolute': 1850, 'engine.boost.spec_absolute': 1980,
  'engine.rpm': 3420, 'engine.ignition_timing': 14.5,
  'engine.timing_retard.cylinder1': 0, 'engine.timing_retard.cylinder2': 1.5,
  'engine.timing_retard.cylinder3': 0, 'engine.timing_retard.cylinder4': .75,
  'engine.fuel_rail.actual': 108, 'engine.fuel_rail.spec': 110,
  'engine.fuel_pump_duty': 62, 'engine.injection_time': 6.4,
  'engine.oil_temperature': 96, 'ambient.filtered_temperature': 21,
  'engine.intake_temperature': 33, 'engine.coolant_temperature': 91,
  'transmission.fluid_temperature': 78, 'transmission.module_temperature': 68,
  'transmission.clutch_oil_temperature': 82, 'transmission.idle_status': 'Driving',
  'transmission.clutch1.shaft_speed': 3420, 'transmission.clutch2.shaft_speed': 2350,
  'transmission.clutch1.specified_torque': 185, 'transmission.clutch2.specified_torque': 0,
  'transmission.clutch1.valve_current': 540, 'transmission.clutch2.valve_current': 210,
  'transmission.clutch1.actual_pressure': 7.4, 'transmission.clutch2.actual_pressure': 2.2,
  'transmission.selector.1_3.travel_distance': 12, 'transmission.selector.2_4.travel_distance': 8,
  'transmission.selector.5_n.travel_distance': 5, 'transmission.selector.6_r.travel_distance': 0,
  'vehicle.speed': 86, 'awd.oil_pressure': 26, 'awd.estimated_torque': 840,
  'awd.valve.opening': 62, 'awd.valve.current': 940, 'awd.commanded_torque': 410,
  'awd.slip_control_torque': 125, 'awd.oil_temperature': 68, 'awd.plate_temperature': 74,
  'awd.supply_voltage': 13.8, 'awd.can_output_signals': 1, 'awd.vehicle_mode': 0,
  'awd.slip_control': 0, 'awd.operating_mode_fault': 0,
};
function samples(t) {
  return Object.entries(values).map(([id, value]) => {
    const entry = catalog.find(v => v.id === id);
    const provider = entry?.providers[0];
    return ({
    version: 1, id, value: typeof value === 'number' && ['engine.rpm', 'engine.maf', 'engine.boost.actual_absolute'].includes(id) ? value * (1 + Math.sin(t) * .15) : value,
    status: 'ok', unit: catalog.find(v => v.id === id)?.unit ?? '', timestamp: Date.now()/1000, age_ms: 0, max_age_ms: 5000, sample_sequence: Math.round(t * 100) + 1,
    source: provider ? { id: `fixture:${provider.id}`, kind: provider.kind } : null, quality: { valid: true, fresh: true, verified: provider?.verified ?? false, estimated: provider?.estimated ?? false, reason: 'Synthetic help-site demo; not an ECU observation' },
  }); });
}
function Capture() {
  const [tab, setTab] = useState(scene.startsWith('data-') ? 'Data & Logs' : scene === 'awd' ? 'AWD' : scene.startsWith('diagnostics') && safeDiagnostics ? 'Diagnostics' : scene === 'transmission' ? 'Transmission' : 'Engine');
  useEffect(() => { let t = 0; DataStore.updateValues(samples(t)); const timer = setInterval(() => { t += .12; DataStore.updateValues(samples(t)); }, 180); return () => clearInterval(timer); }, []);
  // Navigate through production controls so screenshot scenes remain reproducible
  // without editing the production component's state or its layout.
  useEffect(() => {
    if (!scene.startsWith('data-')) return;
    let done = false;
    const timer = setInterval(() => {
      if (done || !document.querySelector('.dl-workflow')) return;
      const click = text => [...document.querySelectorAll('button')].find(button => button.textContent === text)?.click();
      if (scene === 'data-dis' || scene === 'data-slot') click('DIS pages');
      if (scene === 'data-review') {
        click('Review');
        setTimeout(() => { const select = document.querySelector('[aria-label="Saved recording"]'); if (select) { select.value = 'sample-boost-log'; select.dispatchEvent(new Event('change', { bubbles: true })); } }, 50);
      }
      if (scene === 'data-slot') setTimeout(() => document.querySelector('.dl-slot')?.click(), 50);
      if (scene === 'data-picker') click('Choose values');
      if (scene === 'data-recording') click('Start');
      done = true;
    }, 80);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (scene !== 'diagnostics-engine' || !safeDiagnostics) return;
    let cancelled = false;
    const later = () => new Promise(resolve => setTimeout(resolve, 100));
    const clickText = text => [...document.querySelectorAll('button')].find(button => button.textContent === text)?.click();
    (async () => {
      await later();
      [...document.querySelectorAll('#diagnostics button')].find(button => button.textContent.startsWith('Engine'))?.click();
      await later();
      for (const [index, group] of ['3', '20', '115'].entries()) {
        if (cancelled) return;
        document.querySelector(`[placeholder="Grp ${index + 1}"]`)?.click(); await later();
        for (const digit of group) { clickText(digit); await later(); }
        clickText('OK'); await later();
      }
    })();
    return () => { cancelled = true; };
  }, []);
  const palette = { '--primary': '#bddb96', '--on-surface': '#e6e8dd', '--background': '#151912', '--surface': '#1c2218', '--surface-container': '#20271b', '--on-background': '#e6e8dd', '--primary-container': '#354a25', '--on-primary-container': '#daedc5', '--surface-variant': '#424c39', '--on-surface-variant': '#b8c4a9', '--outline': '#839074', '--outline-variant': '#424c39', '--secondary-fixed': '#d5dca0', '--tertiary-fixed': '#e5bd94', '--error': '#ffb4ab', '--surface-tint': '#bddb96' };
  window.hudiy = { colorScheme: { ...Object.fromEntries(Object.entries(palette).map(([key, value]) => [key.slice(2).replace(/-([a-z])/g, (_, char) => char.toUpperCase()), value])), darkThemeEnabled: true } };
  return <div className="container" data-theme="dark" style={palette}><nav className="tabs"><button className="smooth-toggle active">~</button>{['Engine', 'Transmission', 'AWD', 'Data & Logs', 'Diagnostics'].map(name => <button key={name} className={`tab-btn${tab === name ? ' active' : ''}`} onClick={() => (name !== 'Diagnostics' || safeDiagnostics) && setTab(name)}>{name}</button>)}</nav>{tab === 'Engine' ? <EngineTab/> : tab === 'Transmission' ? <TransmissionTab/> : tab === 'AWD' ? <AWDTab socket={fixtureSocket}/> : tab === 'Data & Logs' ? <DataLogsTab socket={fixtureSocket} isActive onValues={() => {}}/> : <DiagnosticsTab/>}</div>;
}
createRoot(document.getElementById('root')).render(<Capture/>);
