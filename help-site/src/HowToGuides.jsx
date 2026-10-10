import React, { useState } from 'react';
import { Figure, Note, PageHead, Related, Section, Settings, SourceLink, Steps, Table } from './ui';
import './how-to-guides.css';

export const howToGroup = { id: 'howto', title: 'HOW TO' };
export const howToTopics = [
  { id: 'apply-update', group: 'howto', title: 'Apply config & update', icon: '↓', summary: 'Put edits on the Pi, choose an update track and keep your setup', keywords: 'install SSH systemd restart backup restore confbackup config.json branch testing release beta upload portal' },
  { id: 'build-readings', group: 'howto', title: 'Build a readings page', icon: '▦', summary: 'An eight-slot page, with units and a linked recording', keywords: 'DIS car_info Daily duplicate precision decimals fixed proportional estimated unverified slots' },
  { id: 'record-a-run', group: 'howto', title: 'Record a useful run', icon: '≋', summary: 'Choose comparable values, mark an event and interpret the CSV', keywords: 'boost absolute specified actual pressure Engine pull temperatures source status stale graph CSV timestamp' },
  { id: 'troubleshooting', group: 'howto', title: 'Find the broken bit', icon: '⊞', summary: 'Display, wheel, missing readings and phone connection checks', keywords: 'debug service systemctl journalctl navigation route disconnect scanner diagnostics API logs blank DIS no wheel' },
];

export function Command({ children, label = 'Run on the Pi' }) {
  const [result, setResult] = useState('');
  async function copy() {
    try { await navigator.clipboard.writeText(children); setResult('Copied'); }
    catch { setResult('Select the command to copy it'); }
  }
  return <div className="howto-command"><div><span>{label}</span><button onClick={copy}>{result || 'Copy'}</button></div><pre><code>{children}</code></pre></div>;
}

function ApplyUpdate() { return <>
  <PageHead location="HOW TO / CONFIG & UPDATES" title="Apply a change. Keep your setup.">Getting config edits onto the Pi, updating, and what survives an update.</PageHead>
  <Section title="Apply a config change"><p>Pick one:</p><ul>
    <li><strong>On the head unit:</strong> edit in <a href="#manager">RNS-E Manager</a> → Settings.</li>
    <li><strong>From your phone or laptop:</strong> edit in the <a href="#configuration">config helper</a> (import your current file first so you keep your settings), download, then upload it in the <a href="#files">file portal</a> → Configuration.</li>
    <li><strong>Over SSH:</strong> copy it to <code>~/config.json</code>.</li>
  </ul><p>Manager and the portal back up the old file. None of them restart anything. Restart from Manager → Services, or:</p><Table headings={['Changed', 'Restart']} rows={[
    ['Center DIS / navigation / cover art', <code>sudo systemctl restart dis_service.service dis_display.service</code>],
    ['Top display', <code>sudo systemctl restart dis_top_display.service</code>],
    ['Buttons & wheel', <code>sudo systemctl restart can_keyboard_control.service</code>],
    ['DataView / file portal / recording folder', <code>sudo systemctl restart hudiy_dataview.service</code>],
  ]}/><p>The DIS services wait 10 seconds on startup, so give it a moment.</p></Section>
  <Section title="Update"><p>Hudiy app menu → <strong>Update RNS-E stuff</strong>, or:</p><Command>{'sudo ~/hudiy_client/update_rnse.sh'}</Command><p>It needs internet (Wi-Fi or your phone’s hotspot), reads <code>repo</code> and <code>branch</code> from <code>~/config.json</code>, and reboots when done. <strong>testing</strong> and <strong>main</strong> follow those branches. Any other name (release, beta) uses the newest matching <code>name-*</code> tag, or the branch of that name. If the ref doesn’t exist, the update cancels. The repo picker on this site doesn’t change any of that.</p></Section>
  <Section title="What survives an update"><ul>
    <li><code>~/config.json</code> and Hudiy’s configs: new keys get added, your values stay. Changed files are backed up first.</li>
    <li><code>~/logs/data-logs/</code>: DIS pages, profiles and recordings aren’t touched.</li>
    <li>Backups go to <code>~/confbackup/YYYY-MM-DD/N/</code>.</li>
  </ul><p>That’s config backups, not a backup of the Pi. Make your own before big changes.</p></Section>
  <Section title="Restore configs"><p><strong>Restore configs</strong> in the Hudiy menu <em>replaces</em> config.json and the Hudiy configs with the ones from <code>config_restore_repo</code> / <code>config_restore_branch</code> (or the update source if those are empty), backs up the old ones, and reboots. If that ref doesn’t exist it falls back to main, so check it first.</p></Section>
  <Section title="First install"><p>See <a href="#install-package">Install this project</a>.</p></Section>
  <Settings rows={[
    ['repo', 'Repo the updater pulls from.'], ['branch', 'Branch or tag channel.'],
    ['config_restore_repo', 'Repo for Restore configs.'], ['config_restore_branch', 'Branch for Restore configs.'],
  ]}/>
  <Related links={[[ 'configuration', 'Edit the config', 'Descriptions for every setting.' ],['troubleshooting','Check the result','Services, logs and symptoms.']]}/>
</>; }

function BuildReadings() { return <>
  <PageHead location="HOW TO / CUSTOM DIS" title="Build a page you’ll actually use">Start from the Daily page, then add pages for whatever you want to watch. What’s on screen and what gets recorded are separate choices.</PageHead>
  <Figure src="dataview-dis-editor.jpg" caption="The Data & Logs page editor. Log: picks the profile the cluster’s play button starts."/>
  <Section title="Steps"><Steps items={[
    ['DataView → Data & Logs → DIS pages', 'Pick Daily, or + for a new page. Page settings renames (12 characters max), duplicates and reorders.'],
    ['Tap a slot, then its value', 'Browse or search by name or ID.'],
    ['Units, decimals, font, icon', 'Auto picks a matching pixel icon. Done.'],
    ['Log: profile, then Apply', '“Unapplied changes” means it’s not saved yet. The profile can record more than the eight values on screen.'],
    ['Show it on the DIS', <>Make sure <code>car_info</code> is in the center app list, stalk to it, double-click MODE, select the page name, scroll, click.</>],
  ]}/></Section>
  <Section title="A starting layout"><Table headings={['Slots', 'Values']} rows={[
    ['1L / 1R', 'Oil temp / coolant temp'],
    ['2L / 2R', 'Intake air temp / transmission fluid temp'],
    ['3L / 3R', 'Boost (actual, absolute) / MAF'],
    ['4L / 4R', 'RPM / Haldex oil temp'],
  ]}/><p>If a value is always unavailable, your car doesn’t send it. Swap it. Boost in bar or psi is still absolute.</p></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Include car_info.'],
    ['display.center_display.high_resolution', 'On for white DIS.'],
    ['data_logs.directory', 'Where pages, profiles and recordings live.'],
  ]}/>
  <Related links={[[ 'readings', 'Wheel control', 'Page select, record, stop and mark.' ],['record-a-run','The linked recording','Picking values worth recording.']]}/>
</>; }

function RecordRun() { return <>
  <PageHead location="HOW TO / DATA & LOGS" title="Record a useful run">Know what you’re looking for, record the values that explain it, and mark the moment.</PageHead>
  <Section title="Pick values"><p>Start from the bundled <strong>Engine pull</strong> profile: select it, press <strong>+</strong>, name your copy, then <strong>Choose values</strong>. Useful pairs:</p><ul>
    <li>RPM + actual and requested boost.</li>
    <li>MAF + intake temp + timing.</li>
    <li>Actual and requested rail pressure + pump duty.</li>
    <li>Oil + coolant temp, so runs are comparable.</li>
  </ul><p>Search works on names and IDs (<code>engine.boost.actual_absolute</code>). Check the values are actually live before you go.</p></Section>
  <Section title="Record"><Steps items={[
    ['Check the live list', 'Each value shows its status. Start is enabled once the profile has values.'],
    ['Start', 'Keeps running if you change tabs. The DIS play button runs the same recording.'],
    ['Mark', 'Or the DIS flag. Gives you something to jump to.'],
    ['Stop & review', 'Pick traces, jump to the marker, tap to inspect, zoom.'],
  ]}/><Figure src="dataview-review.jpg" caption="Review, with synthetic demo values."/></Section>
  <Section title="Reading it"><ul>
    <li><strong>Waiting:</strong> no sample yet. <strong>stale:</strong> too old. <strong>unavailable / invalid:</strong> nothing usable. <strong>paused:</strong> diagnostics are off or busy.</li>
    <li>Bad samples are gaps, not zero. Check Events for status changes.</li>
    <li>The cursor shows each value’s last sample at or before that time. Nothing is interpolated, and channels sample at different times.</li>
    <li>Sparse trace? The ECU can only answer so fast. Fewer diagnostic values helps more than wishing.</li>
  </ul></Section>
  <Section title="CSV"><p><strong>Review → CSV</strong> exports everything, one row per sample or event (not one row per moment). Key columns: <code>id, value, unit, status</code>, timestamps (<code>timestamp, received_at, event_at</code>, all Pi clock), <code>source, quality</code>, and <code>note</code> for markers.</p></Section>
  <SourceLink source="hudiy_dataview/data_logs.py">Recording and CSV behavior</SourceLink>
  <Related links={[[ 'recordings', 'Review controls', 'Time windows, graphs, markers and events.' ],['files','Other logs','Drive Logger CSVs and debug logs.']]}/>
</>; }

function Troubleshooting() { return <>
  <PageHead location="HOW TO / TROUBLESHOOTING" title="Find the broken bit">Start from what still works; it tells you which part broke.</PageHead>
  <Section title="By symptom"><Table headings={['Symptom', 'Check']} rows={[
    ['Center DIS blank, DataView fine', <>Center display enabled and app list, then <code>dis_service</code> and <code>dis_display</code>. Top lines are a separate service.</>],
    ['Wheel won’t select DIS items', 'Be on a readings page or call, then double-click MODE. No wheel icon? The keyboard journal says why.'],
    ['DIS recording saves nothing', <><code>hudiy_dataview</code> runs the recorder, even from the wheel. Check the page’s Log profile.</>],
    ['One value missing', 'Check its status. Your ECU may not send it, or it needs the estimated/unverified opt-in.'],
    ['Diagnostic values stopped, passive ones fine', 'Diagnostics toggled off, a scanner connected, or Flashing Mode is on.'],
    ['Music works, nav blank', 'Is there an actual route with turns being sent?'],
    ['Phone connected, no call page', <>No active call, or <code>claim_on_phone</code> is off.</>],
    ['DIS and diagnostics quiet after flashing', <>Flashing Mode is still on. Turn it off in the Hudiy menu. See <a href="#controllers">Module flashing</a>.</>],
  ]}/><p>Also: the DIS driver does nothing with the ignition off, even though the service is running.</p></Section>
  <Section title="Services and logs"><Command>{'systemctl --no-pager --full status can_handler.service hudiy_status_service.service hudiy_dataview.service hudiy_data_api.service dis_service.service dis_display.service can_keyboard_control.service'}</Command><Command>{'journalctl -u can_keyboard_control.service --since "10 minutes ago" --no-pager'}</Command><p>Swap in whichever service you need. Or use <a href="#manager">RNS-E Manager</a> → Logs. What each service does: <a href="#installed">What got installed</a>.</p></Section>
  <Section title="Where a value comes from"><p><code>http://&lt;Pi-IP&gt;:5003/api/values/status</code> shows which source each value is using and the diagnostic request rates. <code>/api/values/catalog</code> lists every value and its providers.</p></Section>
  <Section title="Report a problem"><Steps items={[
    ['Write down how to trigger it', 'Phone, DIS page, track/call/turn, what you pressed, whether the wheel icon was there.'],
    ['Save Logs right away', 'Before rebooting; live logs are in RAM.'],
    ['Download it', 'File portal → Debug logs. Send it with your notes.'],
  ]}/><Note>API captures can contain street names, contacts and phone numbers.</Note></Section>
  <Settings rows={[
    ['display.center_display.enabled', 'Center display on/off.'], ['display.phone', 'Call page and wheel takeover.'],
    ['input_mappings.mfsw.double_click_ms', 'Double-click timing.'], ['features.log_saver', 'Which services and how many minutes Save Logs keeps.'],
  ]}/>
  <Related links={[[ 'files', 'File portal', 'Debug logs, API captures, flash reports.' ],['controls','Buttons & wheel','Default mappings and DIS gestures.'],['power','Connections & power','Reconnect and shutdown.']]}/>
</>; }

export const HowToPages = {
  'apply-update': ApplyUpdate,
  'build-readings': BuildReadings,
  'record-a-run': RecordRun,
  troubleshooting: Troubleshooting,
};
