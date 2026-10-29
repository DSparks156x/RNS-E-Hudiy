import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TouchTextInput } from './components/touchKeyboard/TouchTextInput';
import { ADC_BUILTIN_PRESETS, ADC_FIELDS, AdcField, AdcPage, AdcPreset, AdcSnapshot, adcCommandsBusy, adcDisplayByte, adcField, adcFieldWritableNow, adcWriteMessage, CLAMP_LIMIT, decodeAdcField, encodeAdcField, fieldRegisters, ReleasedDraft, suggestedVcoRange, validateClampWindow } from './rnseAdcModel';
import './rnseAdcPanel.css';

type Api = <T>(path:string, init?:RequestInit)=>Promise<T>;
interface Props { api:Api; pin?:string; onTestPattern:()=>void; }
type Page=AdcPage|'dump';
const headers=(pin:string)=>({'Content-Type':'application/json','X-Hudiy-Management':'1',...(pin?{'X-Hudiy-Pin':pin}:{})});
const hex=(n:number|null|undefined)=>n==null?'—':`0x${n.toString(16).padStart(2,'0').toUpperCase()}`;
// Built-in preset: the backend revert writes the firmware register values.
const FIRMWARE_PRESET='Firmware (revert)';
const PAGES:[Page,string][]=[['clock','Clock'],['gain','Gain'],['black','Black'],['clamp','Clamp'],['sync','Sync'],['output','Output'],['dump','Registers']];
const HINTS:Record<AdcPage,string>={
 clock:'Line length must equal the Pi Htotal (1014). VCO range must contain the pixel clock. TV mode changes overwrite 01–03: press Re-send clock afterwards.',
 gain:'Lower gain means more contrast. 0x70 gives white ≈ 252 from a 0.70 V source.',
 black:'Manual offsets only apply with black loop mode Off. Banding fix candidate: correction update every 64 frames.',
 clamp:`Clamp start + length ≤ ${CLAMP_LIMIT} (camera-safe end ≤ 69). Split must be less than the clamp length. Try clamp coast 3/3 if the top flickers.`,
 sync:'HSYNC pin may not be wired: if lock is lost, select SOG slicer again. Keep PLL coast total under 45 lines.',
 output:'Drive ¼ lowers static noise. HSYNC width may shift the capture window.',
};

function Slider({field,value,known,disabled,status,syncToken,onCommit}:{field:AdcField;value:number;known:boolean;disabled:boolean;status:string;syncToken:number;onCommit:(v:number)=>void}){
 const [draft,setDraft]=useState(value); const gesturing=useRef(false); const values=useRef(new ReleasedDraft(value));
 useEffect(()=>{if(!gesturing.current){values.current.sync(value);setDraft(value);}},[value,syncToken]);
 const change=(v:number)=>{values.current.change(v);setDraft(v);};
 const release=()=>{gesturing.current=false;const v=values.current.release();if(v!==null)onCommit(v);};
 const step=(n:number)=>{change(Math.max(field.min,Math.min(field.max,draft+n)));release();};
 const id=`adc-${field.id}`,shown=`${field.detail?field.detail(draft):draft}${known?'':' ?'}`;
 return <div className="adc-control"><div className="adc-control-head"><label htmlFor={id}>{field.label}{field.widen&&<abbr title="Needs the BC widening patch"> W</abbr>}</label><output htmlFor={id}>{shown}</output></div><div className="adc-range"><button type="button" aria-label={`Decrease ${field.label}`} disabled={disabled||draft<=field.min} onClick={()=>step(-1)}>−</button><input id={id} type="range" min={field.min} max={field.max} step="1" value={draft} disabled={disabled} aria-label={field.label} onPointerDown={e=>{gesturing.current=true;e.currentTarget.setPointerCapture(e.pointerId);}} onChange={e=>change(Number(e.target.value))} onPointerUp={release} onPointerCancel={()=>{gesturing.current=false;setDraft(values.current.cancel());}} onKeyDown={()=>{gesturing.current=true;}} onKeyUp={release} onBlur={release}/><button type="button" aria-label={`Increase ${field.label}`} disabled={disabled||draft>=field.max} onClick={()=>step(1)}>+</button></div><small className="adc-control-status">{status}</small></div>;
}

function Choice({field,value,known,disabled,status,onCommit}:{field:AdcField;value:number;known:boolean;disabled:boolean;status:string;onCommit:(v:number)=>void}){
 const options=Array.from({length:field.max-field.min+1},(_,i)=>field.min+i);
 return <div className="adc-control"><div className="adc-control-head"><span>{field.label}{field.widen&&<abbr title="Needs the BC widening patch"> W</abbr>}</span>{!known&&<output>?</output>}</div><div className="adc-choice" role="radiogroup" aria-label={field.label}>{options.map(v=><button key={v} type="button" role="radio" aria-checked={known&&value===v} className={known&&value===v?'active':''} disabled={disabled} onClick={()=>{if(!known||v!==value)onCommit(v);}}>{field.detail?field.detail(v):v}</button>)}</div><small className="adc-control-status">{status}</small></div>;
}

export function RnseAdcPanel({api,pin='',onTestPattern}:Props){
 const [page,setPage]=useState<Page>('gain'),[snapshot,setSnapshot]=useState<AdcSnapshot|null>(null),[presets,setPresets]=useState<Record<string,AdcPreset>>({}),[presetName,setPresetName]=useState(''),[selected,setSelected]=useState(''),[linked,setLinked]=useState(true),[advanced,setAdvanced]=useState(false);
 const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[syncVersion,setSyncVersion]=useState(0);
 const busyRef=useRef(false),requestEpoch=useRef(0),alive=useRef(false),snapshotRef=useRef<AdcSnapshot|null>(null);
 useEffect(()=>{if(!notice&&!error)return undefined;const timer=window.setTimeout(()=>{setNotice('');setError('');},error?8000:3500);return()=>window.clearTimeout(timer);},[notice,error]);
 const refresh=useCallback(async()=>{if(busyRef.current)return;const epoch=requestEpoch.current;try{const next=await api<AdcSnapshot>('/rnse-adc');if(alive.current&&!busyRef.current&&epoch===requestEpoch.current){snapshotRef.current=next;setSnapshot(next);}}catch(e){if(alive.current&&!busyRef.current&&epoch===requestEpoch.current&&!snapshotRef.current)setError(e instanceof Error?e.message:'ADC controls unavailable.');}finally{if(alive.current)setLoading(false);}},[api]);
 const refreshPresets=useCallback(async()=>{try{const result=await api<{presets?:Record<string,AdcPreset>}>('/rnse-adc/presets');setPresets(result.presets||{});}catch{/* Preset support can arrive independently of live control. */}},[api]);
 useEffect(()=>{alive.current=true;void refresh();void refreshPresets();const timer=window.setInterval(()=>void refresh(),500);return()=>{alive.current=false;window.clearInterval(timer);};},[refresh,refreshPresets]);
 const byte=useCallback((register:string)=>adcDisplayByte(snapshot,register),[snapshot]);
 const live=useMemo(()=>Object.fromEntries(ADC_FIELDS.map(field=>[field.id,decodeAdcField(field,byte)])) as Record<string,number|null>,[byte]);
 const value=(id:string)=>live[id]??adcField(id).firmware;
 const request=async(path:string,body?:unknown)=>{if(busyRef.current||!snapshotRef.current||adcCommandsBusy(snapshotRef.current))return;busyRef.current=true;requestEpoch.current++;setBusy(true);setSyncVersion(v=>v+1);setError('');setNotice('');try{const next=await api<AdcSnapshot>(path,{method:'POST',headers:headers(pin),body:JSON.stringify(body||{})});if(!alive.current)return;snapshotRef.current=next;setSnapshot(next);if(next.command_error)setError(next.command_error);else if(Object.values(next.writes||{}).some(write=>write.state==='queue_failed'||write.state==='not_sent'))setError('One or more register writes were not sent. Check each control status.');else if(path.endsWith('/dump'))setNotice('Dump requested; waiting for all register frames.');else if(path.endsWith('/revert'))setNotice('Firmware values sent; check each register status.');else setNotice('Request sent; check each control status for readback.');}catch(e){if(alive.current)setError(e instanceof Error?e.message:'ADC request failed.');}finally{busyRef.current=false;if(alive.current)setBusy(false);}};
 const write=async(values:AdcPreset)=>request('/rnse-adc/write',{values});
 const commit=(field:AdcField,v:number)=>{
  setSyncVersion(n=>n+1);
  const start=field.id==='clampStart'?v:value('clampStart'),length=field.id==='clampLength'?v:value('clampLength'),split=field.id==='clampSplit'?v:value('clampSplit');
  if(['clampStart','clampLength','clampSplit'].includes(field.id)){if(!validateClampWindow(start,length)){setError(`Clamp start + length must stay at or below ${CLAMP_LIMIT} clocks.`);return;}if(split>=length){setError('Clamp/black-loop split must be less than the clamp length.');return;}}
  const group=linked&&field.page==='gain'?['gainR','gainG','gainB']:[field.id];
  let values:AdcPreset={};
  try{for(const id of group)values={...values,...encodeAdcField(adcField(id),v,byte)};}catch(e){setError(e instanceof Error?e.message:'Invalid ADC value.');return;}
  void write(values);
 };
 const runAction=(path:string)=>request(path,{});
 const savePreset=async()=>{const name=presetName.trim();if(!name){setError('Enter a preset name.');return;}if(busyRef.current||!snapshotRef.current)return;busyRef.current=true;requestEpoch.current++;setBusy(true);setError('');try{await api('/rnse-adc/presets',{method:'POST',headers:headers(pin),body:JSON.stringify({name,values:knownBytes(live,byte)})});if(!alive.current)return;await refreshPresets();setSelected(name);setNotice(`Saved preset “${name}”.`);}catch(e){if(alive.current)setError(e instanceof Error?e.message:'Could not save preset.');}finally{busyRef.current=false;if(alive.current)setBusy(false);}};
 const loadPreset=()=>{if(selected===FIRMWARE_PRESET){void runAction('/rnse-adc/revert');return;}const values=ADC_BUILTIN_PRESETS[selected]??presets[selected];if(values)void write(values);};
 const reg=(address:string)=>snapshot?.registers?.find(r=>r.register.toUpperCase()===address);
 const fieldStatus=(field:AdcField)=>{
  const regs=fieldRegisters(field),messages=regs.map(r=>[r,adcWriteMessage(snapshot,r)] as const).filter(([,m])=>m);
  const failed=messages.find(([r])=>!['ok','queued','pending','queued_unconfirmed'].includes(snapshot?.writes?.[r]?.state||''));
  if(failed)return failed[1];
  if(messages.length)return messages[messages.length-1][1];
  if(live[field.id]!=null)return regs.every(r=>reg(r)?.in_dump)?`Dump ${regs.map(r=>hex(reg(r)?.value)).join(' ')}`:'Last written value';
  return adcFieldWritableNow(field)?'Not read yet · Dump to read':regs.some(r=>reg(r)?.in_dump)?'Dump to read · needs BC widening':'Not in dump · needs BC widening';
 };
 const commandActive=adcCommandsBusy(snapshot);
 const disabled=busy||loading||!snapshot||snapshot.inhibited===true||snapshot.radio_active===false||commandActive;
 const clockTuned=Object.keys(snapshot?.clock_tuned||{}).length>0;
 const dumpState=snapshot?.dump?.state;
 const status=loading?'Loading…':snapshot?.inhibited?'Paused':snapshot?.radio_active===false?'Radio inactive':[dumpState&&dumpState!=='complete'&&dumpState!=='idle'?`Dump ${dumpState}${snapshot?.dump?.received_sequences?.length?` ${snapshot.dump.received_sequences.length}/8`:''}`:null,`Reply ${snapshot?.reply_id==null?'—':hex(snapshot.reply_id)}`,page==='dump'?null:snapshot?.state||'Ready'].filter(Boolean).join(' · ');
 const control=(field:AdcField)=>{
  const known=live[field.id]!=null,props={field,value:value(field.id),known,status:fieldStatus(field),onCommit:(v:number)=>commit(field,v),disabled:disabled||(field.advanced===true&&!advanced)};
  return field.max-field.min<=3?<Choice key={field.id} {...props}/>:<Slider key={field.id} {...props} syncToken={syncVersion}/>;
 };
 const vcoHint=page==='clock'?` Suggested VCO range for ${value('lineLength')} clocks: ${suggestedVcoRange(value('lineLength'))}.`:'';
 return <section className="rnse-adc" aria-label="RNS-E ADC tuning">
   <div className="adc-toolbar"><div className="adc-pages" role="tablist" aria-label="ADC sections">{PAGES.map(([id,label])=><button key={id} role="tab" aria-selected={page===id} className={page===id?'active':''} onClick={()=>setPage(id)}>{label}</button>)}</div><div className="adc-actions"><span aria-live="polite">{status}</span>{page==='gain'&&<label className="adc-link"><input type="checkbox" checked={linked} onChange={e=>setLinked(e.target.checked)}/> Link RGB</label>}{page==='dump'&&<button type="button" disabled={disabled} onClick={()=>void runAction('/rnse-adc/dump')}>Dump</button>}<button type="button" disabled={busy} onClick={onTestPattern}>Test image</button></div></div>
   {(error||notice)&&<div className={`manager-message ${error?'error':''}`} role={error?'alert':'status'} onClick={()=>{setError('');setNotice('');}}><span>{error||notice}</span></div>}
   {page!=='dump'&&<div className="adc-page-content">{page==='clock'&&<div className="adc-page-actions"><label className="adc-link"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/> Unlock line length</label><button type="button" disabled={disabled||!clockTuned} title="Re-send the last confirmed 01–03 after a TV mode change" onClick={()=>void runAction('/rnse-adc/resend-clock')}>Re-send clock</button></div>}<div className="adc-control-grid">{ADC_FIELDS.filter(field=>field.page===page).map(control)}</div><p className="adc-hint">{HINTS[page]}{vcoHint} W = needs the BC widening patch. Writes are lost on reboot and stay active for the reverse camera until then.</p></div>}
   {page==='dump'&&<div className="adc-page-content adc-dump"><div className="adc-registers" role="table" aria-label="ADC registers"><div className="adc-register-row adc-register-head" role="row"><span>Reg</span><span>Current</span><span>Baseline</span><span>Status</span></div>{(snapshot?.registers||[]).map(item=><div className={`adc-register-row ${item.changed?'changed':''} ${item.failed?'failed':''}`} role="row" key={item.register}><span>{item.register.toUpperCase()}</span><span>{hex(item.value)}</span><span>{item.in_dump===false?'—':hex(item.baseline)}</span><span>{item.failed?'Read failed':adcWriteMessage(snapshot,item.register.toUpperCase())||[item.changed?'Changed':null,item.in_dump===false?'Not in dump · last written':null,item.access==='read_only'?'Read-only':item.access==='widen'?'Needs BC widening':null].filter(Boolean).join(' · ')||'—'}</span></div>)}</div><div className="adc-preset-tools"><TouchTextInput value={presetName} onValueChange={setPresetName} aria-label="Preset name" placeholder="Preset name" maxLength={40} disabled={disabled}/><button type="button" disabled={disabled||!presetName.trim()} onClick={()=>void savePreset()}>Save preset</button><select aria-label="ADC preset" value={selected} disabled={disabled} onChange={e=>setSelected(e.target.value)}><option value="">Choose preset</option><option value={FIRMWARE_PRESET}>{FIRMWARE_PRESET}</option>{Object.keys(ADC_BUILTIN_PRESETS).map(name=><option key={name}>{name}</option>)}{Object.keys(presets).filter(name=>name!==FIRMWARE_PRESET&&!(name in ADC_BUILTIN_PRESETS)).map(name=><option key={name}>{name}</option>)}</select><button type="button" disabled={disabled||!selected} onClick={loadPreset}>Load</button></div></div>}
 </section>;
}
// Only controls with a known value; shared registers merge into one byte.
function knownBytes(live:Record<string,number|null>,byte:(register:string)=>number|null):AdcPreset {let result:AdcPreset={};for(const field of ADC_FIELDS){const v=live[field.id];if(v!=null)result={...result,...encodeAdcField(field,v,register=>result[register]??byte(register))};}return result;}
