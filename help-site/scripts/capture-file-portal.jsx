// Safe capture fixture: actual portal UI, in-memory files, no network or controller APIs.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { FilePortal } from '../../hudiy_dataview/src/FilePortal';
import '../../hudiy_dataview/static/css/style_v3.css';

const params = new URLSearchParams(location.search);
const darkTheme = {
  darkThemeEnabled:true, background:'#101510', surface:'#1a211a', surfaceContainer:'#1a211a', surfaceDim:'#101510',
  onSurface:'#e0e6dc', onBackground:'#e0e6dc', primary:'#adcda1', onPrimary:'#16380f',
  primaryContainer:'#2c5024', onPrimaryContainer:'#c8e9bb', surfaceVariant:'#404a3c',
  onSurfaceVariant:'#c0cbb9', outline:'#899581', outlineVariant:'#3f4a39', error:'#ffb4ab',
  errorContainer:'#93000a', onErrorContainer:'#ffdad6',
};
const lightTheme = {
  ...darkTheme, darkThemeEnabled:false, background:'#f6faf0', surface:'#ebf0e5', surfaceContainer:'#ebf0e5', surfaceDim:'#e0e6da',
  onSurface:'#191e16', onBackground:'#191e16', primary:'#46663b', onPrimary:'#ffffff', primaryContainer:'#c8e9bb',
  onPrimaryContainer:'#17370f', surfaceVariant:'#dce5d4', onSurfaceVariant:'#444d3e', outline:'#747e6d', outlineVariant:'#c4cebb',
};
const theme = params.get('theme') === 'light' ? lightTheme : darkTheme;
const definitions = [
  ['firmware_haldex','Haldex AWD','Validated controller firmware images','firmware',['.bin'],[['OpenHaldex_S3_2026-10-06.bin',327680],['Haldex_Stock_Backup.bin',327680]]],
  ['firmware_pq-eps','PQ EPS','Validated full images or 4 KiB 0x5E steering datasets','firmware',['.bin'],[['EPS_3001_full.bin',393216],['EPS_dataset_3001.bin',4096]]],
  ['firmware_exhaust-valve','Exhaust valve controller','SB2209 can-update.json and both native slot .bin images','firmware',['.zip','.json','.bin'],[['exhaust_bundle_2026-10-07.zip',434021],['can-update.json',1528]]],
  ['drive_logs','Drive & DataView logs','CSV recordings created by logger profiles','logs',['.csv'],[['haldex_20261008_092300_104223.csv',289340],['raw_can_20261007_181100_482910.csv',1278340],['haldex_20261006_104600_713822.csv',390340],['haldex_20261004_162000_173409.csv',129340]]],
  ['service_logs','Service & error logs','Saved journal output from Hudiy services','logs',['.log','.txt'],[['2026-10-08/3/rnse_control_3.log',34021],['2026-10-08/3/dis_service_3.log',584032],['2026-10-08/3/hudiy_data_3.log',183401],['2026-10-08/3/vehicle_service_3.log',40231]]],
  ['runtime_logs','Live service logs','Current service output and errors from the in-memory log store','logs',['.log','.txt'],[['rnse_control.log',80431],['dis_service.log',434022],['vehicle_service.log',452034]]],
  ['hudiy_api','Hudiy API captures','Provider-tagged projection, media, navigation, and phone events','logs',['.log'],[['hudiy-api-events.log',304231]]],
  ['flash_logs','Flashing operation logs','Detailed reports from controller read and write operations','logs',['.log'],[['2026-10-07_1545_haldex_read.log',194031],['2026-10-06_1011_eps_read.log',209132]]],
  ['readouts','Haldex readouts','Haldex firmware images and capture reports','readouts',['.bin','.json'],[['haldex_readout_2026-10-07.bin',327680],['haldex_readout_2026-10-07.json',2841]]],
  ['eps_readouts','PQ EPS readouts','EPS firmware, EEPROM images, and capture reports','readouts',['.bin','.json'],[['eps_firmware_2026-10-06.bin',393216],['eps_eeprom_2026-10-06.bin',1024],['eps_readout_2026-10-06.json',8031]]],
];
const collections = definitions.map(([id,label,description,kind,extensions,items],index) => {
  const files = items.map(([path,size],i) => ({name:path.split('/').pop(),path,size,modified:1791478800-index*300-i*3600,download_url:`data:text/plain,Sample%20${encodeURIComponent(path)}`}));
  return {id,label,description,kind,extensions,upload:kind==='firmware',max_size:id==='firmware_exhaust-valve'?1024*1024:4*1024*1024,count:files.length,total_size:files.reduce((sum,f)=>sum+f.size,0),archive_url:'data:application/zip;base64,UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==',files};
});
const catalog = {pin_required:params.get('pin')==='1',all_logs_archive_url:'data:application/zip;base64,UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA==',collections};
const loadCatalog = async () => structuredClone(catalog);
const sendFile = async (target,file,pin,progress) => {
  progress(100);
  const collection = catalog.collections.find(item => item.id === target);
  collection.files.unshift({name:file.name,path:file.name,size:file.size,modified:1791482400,download_url:'data:text/plain,Sample%20upload'});
  collection.count++; collection.total_size += file.size;
  return `${file.name} validated and saved to ${collection.label}.`;
};
const scene = params.get('scene') || 'recordings';
const initialGroup = scene === 'upload' ? 'controllers' : scene === 'debug' ? 'debug' : 'recordings';
const initialCollection = scene === 'upload' ? 'firmware_haldex' : scene === 'debug' ? 'service_logs' : 'drive_logs';
createRoot(document.getElementById('root')).render(<FilePortal previewTheme={theme} loadCatalog={loadCatalog} sendFile={sendFile} initialGroup={initialGroup} initialCollection={initialCollection} />);
