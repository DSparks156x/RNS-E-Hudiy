import React, { useState } from 'react';
import { Figure, Note, PageHead, Related, Section, Settings, SourceLink, Steps, Table } from './ui';
import './how-to-guides.css';

export const howToGroup = { id: 'howto', title: 'HOW TO' };
export const howToTopics = [
  { id: 'apply-update', group: 'howto', title: 'Apply config & update', icon: '↓', summary: 'Put edits on the Pi, choose an update track and keep your setup', keywords: 'install SSH systemd restart backup restore confbackup config.json branch testing release beta' },
  { id: 'build-readings', group: 'howto', title: 'Build a readings page', icon: '▦', summary: 'An eight-slot page, with units and a linked recording', keywords: 'DIS car_info Daily duplicate precision decimals fixed proportional estimated unverified slots' },
  { id: 'record-a-run', group: 'howto', title: 'Record a useful run', icon: '≋', summary: 'Choose comparable values, mark an event and interpret the CSV', keywords: 'boost absolute specified actual pressure Engine pull temperatures source status stale graph CSV timestamp' },
  { id: 'troubleshooting', group: 'howto', title: 'Find the broken bit', icon: '⊞', summary: 'Display, wheel, missing readings and phone connection checks', keywords: 'debug service systemctl journalctl navigation route disconnect scanner diagnostics API logs blank DIS no wheel' },
];

function Command({ children, label = 'Run on the Pi' }) {
  const [result, setResult] = useState('');
  async function copy() {
    try { await navigator.clipboard.writeText(children); setResult('Copied'); }
    catch { setResult('Select the command to copy it'); }
  }
  return <div className="howto-command"><div><span>{label}</span><button onClick={copy}>{result || 'Copy'}</button></div><pre><code>{children}</code></pre></div>;
}

function ApplyUpdate() { return <>
  <PageHead location="HOW TO / CONFIG & UPDATES" title="Apply a change. Keep your setup.">The config helper downloads a file to your computer. Installing it on the Pi is a separate step. An update and a config restore also do different jobs.</PageHead>
  <Section title="Apply an edited config"><Steps items={[
    ['Start with the config already on the Pi', <>Copy <code>~/config.json</code> to your computer and import it in the <a href="#configuration">config helper</a>. Loading a branch’s defaults is useful for comparison; importing your installed file keeps your existing choices.</>],
    ['Download and replace the file', <>Export <code>config.json</code>, keep a copy of the old file, then use your SSH/SFTP client to replace the installed one. The normal Pi setup uses <code>/home/pi/config.json</code>. The downloaded filename alone does not apply anything.</>],
    ['Restart the services that use the changed settings', 'Center-display layout/navigation/artwork changes need both DIS services. Top-display changes use their own service. Button changes use the keyboard service. Check the result before changing another group.'],
  ]}/><Table headings={['Changed settings', 'Restart']} rows={[
    ['Center DIS / navigation / cover art', <code>sudo systemctl restart dis_service.service dis_display.service</code>],
    ['Top display', <code>sudo systemctl restart dis_top_display.service</code>],
    ['Buttons & wheel', <code>sudo systemctl restart can_keyboard_control.service</code>],
    ['DataView / file portal / recording directory', <code>sudo systemctl restart hudiy_dataview.service</code>],
  ]}/><p>The installed center-DIS services each have a 10-second startup delay. A restart can take a moment to show anything.</p></Section>
  <Section title="Choose an update track"><p><code>repo</code> and <code>branch</code> in the installed config choose the code source. <strong>testing</strong> follows the literal testing branch; <strong>main</strong> follows main. Other names, including release and beta, first look for the newest matching <code>name-*</code> tag, then use the literal branch if no tag exists.</p><p>The updater prints the selected repository and branch/tag. A missing reference cancels the update. Your guide’s repository dropdown only chooses what the browser loads; it does not change the Pi’s update track.</p><Command>{'sudo ~/hudiy_client/update_rnse.sh'}</Command><p>The Hudiy update action runs this workflow too: it waits for GitHub access, downloads the selected installer and reboots afterward. Give the Pi internet through Wi-Fi or your hotspot.</p></Section>
  <Section title="What survives an update?"><Table headings={['Stored item', 'Update behavior']} rows={[
    [<code>~/config.json</code>, 'Adds missing JSON keys while keeping existing preferences; also removes obsolete API-capture settings. A changed file is backed up before replacement.'],
    [<code>~/.hudiy/share/config/*.json</code>, 'Hudiy configs are merged too. The installer includes a specific migration that adds the exhaust-valve shortcut.'],
    [<code>~/logs/data-logs/workspace.json</code>, 'Custom DIS pages and named recording profiles live separately from the shipped config. The installer does not replace them.'],
    [<code>~/logs/data-logs/sessions/</code>, 'Saved named recordings remain in their recording store. Use your configured data_logs.directory if changed.'],
    [<code>~/confbackup/YYYY-MM-DD/number/</code>, 'Previous project/Hudiy configs from installer changes, grouped into numbered backup folders.'],
  ]}/><p>Keep your own copy of these files before making a large setup change. The automatic backups cover configs the installer changes, not an image of the whole Pi.</p></Section>
  <Section title="Restore is a replacement"><p><strong>Restore configs</strong> replaces the project config and shipped Hudiy configs from <code>config_restore_repo</code> / <code>config_restore_branch</code>, falling back to the update source when those are empty. It backs up the files it replaces and reboots. Use it when you want the repository’s config, rather than to install one setting.</p><p>The current restore script can fall back to main if its requested reference is missing. Confirm the restore source before using that action.</p></Section>
  <Section title="First installation"><p>Get <code>hudiy_client/update_rnse.sh</code> from the repository you intend to install, put it on the Pi, then run it in install mode:</p><Command>{'sudo bash ./update_rnse.sh --install'}</Command><p>The installer deploys runtime folders into the Pi account’s home and creates systemd services. Configure the Pi’s CAN hardware overlay, CAN device names and video/power wiring for your setup; the installer cannot infer the hardware you wired.</p><SourceLink source="README.md">Hardware and installation notes</SourceLink><SourceLink source="install.sh">Installer behavior</SourceLink><SourceLink source="hudiy_client/update_rnse.sh">Update-track selection</SourceLink></Section>
  <Settings rows={[
    ['repo', 'Code repository used by the Pi updater.'], ['branch', 'Code branch or matching tag channel.'],
    ['config_restore_repo', 'Separate repository for replacing configs.'], ['config_restore_branch', 'Separate config-restore branch/channel.'],
  ]}/>
  <Related links={[[ 'configuration', 'Edit the config', 'Full descriptions and source selection.' ],['troubleshooting','Check the result','Services, logs and symptoms.']]}/>
</>; }

function BuildReadings() { return <>
  <PageHead location="HOW TO / CUSTOM DIS" title="Build a page you’ll actually use">Make a Daily page for temperatures and a second page for the values you want to compare. The eight visible slots and the values recorded by its linked profile are independent choices.</PageHead>
  <Figure src="dataview-dis-editor.jpg" caption="The actual Data & Logs editor. Each row has left/right slots; its Log selector chooses the profile started by the cluster’s play control."/>
  <Section title="Start with the Daily page"><Steps items={[
    ['Open DataView → Data & Logs → DIS pages', 'Choose Daily. Page settings can rename it, duplicate it or change its order. The + button makes a new page. Keep a short name: the touchscreen name field allows 12 characters.'],
    ['Pick a slot, then choose its value', 'The slots are 1L / 1R through 4L / 4R. Tap the value in the slot editor to browse the catalog. Search by a readable label or value ID. Check its provider information before choosing it.'],
    ['Choose how it reads on the cluster', 'Set Units, Decimals, Native text font and icon. Auto uses the project’s matching pixel symbol; the picker shows the cluster artwork. Done returns the edited slot to the page draft.'],
    ['Choose a Log profile, then Apply', 'Apply saves all page edits, including their linked profile. “Unapplied changes” means they are still a draft. The recording profile can include more values than the eight visible slots.'],
    ['Open the page on the DIS', <>Include <code>car_info</code> in the center display app list, then cycle to it with the stalk. Double-click MODE to give the wheel control; select the page name, scroll and click to confirm a subpage.</>],
  ]}/></Section>
  <Section title="A useful starting layout"><Table headings={['Slots', 'Example values', 'Presentation']} rows={[
    ['1L / 1R', 'Engine oil temperature / Coolant temperature', '°C or °F, no decimals'],
    ['2L / 2R', 'Intake air temperature / Transmission fluid temperature', '°C or °F, no decimals'],
    ['3L / 3R', 'Boost pressure (actual absolute) / Mass air flow', 'bar with 2 decimals / source unit'],
    ['4L / 4R', 'Engine speed / Haldex oil temperature', 'RPM / °C or °F'],
  ]}/><p>That is a layout idea, not a promise that every fitted ECU supplies each reading. Replace a consistently unavailable transmission or AWD value with something your car actually reports.</p><p>Pressure conversion changes units, not the reference: <strong>actual absolute</strong> boost remains absolute when displayed in bar or psi. It does not become gauge boost.</p></Section>
  <Section title="Reading the result"><p><strong>Source unit</strong> follows the catalog or returned ECU unit. A selected °F/bar/psi conversion belongs to that slot. The config helper’s legacy unit choices do not override it.</p><p>Estimated and unverified sources are separate opt-ins, available in the slot editor where relevant. Enabling one permits that provider; it does not verify its formula or make a missing ECU field appear.</p><p>The eight-slot layout uses the native white DIS with <code>high_resolution</code> enabled. A red DIS uses its five-line layout. If numbers seem dead, investigate source status before rearranging the page.</p></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Include car_info and choose its position in the stalk cycle.'],
    ['display.center_display.high_resolution', 'Select native white-display rendering or the red-display layout.'],
    ['data_logs.directory', 'Store shared pages/profiles and named recordings.'],
  ]}/>
  <SourceLink source="hudiy_dataview/src/tabs/DataLogsTab.tsx">Page-editor behavior</SourceLink><SourceLink source="vehicle_data/workspace.py">Saved page/profile format</SourceLink>
  <Related links={[[ 'readings', 'See wheel control in action', 'Page selection, record, stop and marker focus.' ],['record-a-run','Build the linked recording','Choose the values you need to compare.']]}/>
</>; }

function RecordRun() { return <>
  <PageHead location="HOW TO / DATA & LOGS" title="Record a useful run">Start with a question: what changed when boost dropped, a temperature climbed or the AWD mode changed? Pick the related values and mark the moment so you can find it again.</PageHead>
  <Section title="Choose values that explain each other"><p>The bundled <strong>Engine pull</strong> profile is a starting point for comparing engine demand with the response. Select it on Record, press <strong>+</strong> and name a new profile. The new profile starts with the selected profile’s values; use <strong>Choose values</strong> to keep your version focused.</p><Table headings={['Compare', 'Why keep them together']} rows={[
    ['Engine speed + actual/spec’d absolute boost', 'Compare boost response with the request at the same RPM. Both pressure values use an absolute reference.'],
    ['Mass air flow + intake temperature + ignition timing', 'Give airflow and timing changes some context instead of reading a pressure trace alone.'],
    ['Actual/spec’d fuel rail pressure + fuel-pump duty', 'Distinguish the requested pressure from its response and accompanying control effort.'],
    ['Oil + coolant temperature', 'Keep the operating conditions with the event so separate recordings are easier to compare.'],
  ]}/><p>Search uses both readable names and IDs, such as <code>engine.boost.actual_absolute</code> and <code>engine.fuel_rail.spec</code>. Provider availability depends on the ECU. Choose values that show usable live readings before starting.</p></Section>
  <Section title="Capture, mark, review"><Steps items={[
    ['Check the live profile', 'Record shows the selected values and their source status. Estimated/unverified providers need the profile’s explicit opt-in. Start is enabled when the profile has values.'],
    ['Start once; keep the session running', 'The recorder continues when you leave Data & Logs. A linked DIS page can start/stop this same recording; it is not a second logger.'],
    ['Mark the event', 'Mark adds a timestamped Driver marker. The DIS flag does the same job. A marker gives Review a useful place to jump to.'],
    ['Stop & review', 'This saves the recording and opens its recent section. Select the traces, jump to the marker, tap the graph to inspect a moment and zoom around it.'],
  ]}/><Figure src="dataview-review.jpg" caption="Review groups traces by recorded units and lets you inspect a time cursor. These demonstration values are synthetic."/></Section>
  <Section title="A gap is information"><Table headings={['Source state', 'Interpretation']} rows={[
    ['Waiting', 'The UI has not received a sample for that selected value yet.'],
    ['ok', 'The sample is currently usable.'],
    ['stale', 'The last acquisition is too old. Re-publishing a cached number does not refresh its timestamp.'],
    ['unavailable / invalid', 'No usable provider/reading, or a decoding/validity check failed.'],
    ['paused', 'Acquisition is inhibited; for example diagnostics may be disabled or held by another workflow.'],
  ]}/><p>Review draws gaps for unusable samples. Do not treat a missing trace as zero pressure or a steady measurement. Check Events for status changes and nonnumeric readings.</p><p>Requested diagnostic rates are not a guarantee of achieved ECU sampling speed. If the trace is sparse, check the source and achieved rates before asking more values to update faster.</p></Section>
  <Section title="Read the cursor correctly"><p>Graphs are grouped by the units actually recorded. When you tap a graph, each inspected value is its last acquired sample at or before the cursor. Review does not interpolate a new measurement between samples; two channels can have different acquisition times.</p><p>An unusable sample still updates the inspected status. The number becomes a dash rather than keeping the last good value as if it were current.</p></Section>
  <Section title="Take the full result with you"><p><strong>Review → CSV</strong> exports the complete saved session, including portions beyond the on-screen sample limit. The export contains one row per recorded sample/event, rather than one perfectly synchronized row containing every channel.</p><Table headings={['CSV fields', 'Use']} rows={[
    [<code>kind, id, value, unit, status</code>, 'Identify the event/value, its recorded units and whether the sample was usable.'],
    [<code>timestamp, received_at, event_at</code>, 'Original host acquisition/receipt time, recording receipt time and event placement; these are not ECU-clock timestamps.'],
    [<code>source, quality, max_age_ms</code>, 'Provider metadata and validity/freshness context.'],
    [<code>note</code>, 'Marker/event text.'],
  ]}/><p>These named recordings live under <code>data_logs.directory</code>, normally <code>~/logs/data-logs</code>. The separate AWD Drive Logger writes Haldex fused/Raw CAN CSVs downloadable from the file portal.</p></Section>
  <SourceLink source="vehicle_data/workspace.py">Bundled profiles</SourceLink><SourceLink source="hudiy_dataview/data_logs.py">Recording and CSV behavior</SourceLink><SourceLink source="vehicle_data/README.md">Source and freshness rules</SourceLink>
  <Related links={[[ 'recordings', 'Review controls', 'Time windows, graphs, markers and events.' ],['files','Download the other logs','Drive Logger CSVs, service journals and API captures.']]}/>
</>; }

function Troubleshooting() { return <>
  <PageHead location="HOW TO / TROUBLESHOOTING" title="Find the broken bit">Start with what still works. A live touchscreen with a blank cluster, a working normal wheel with no DIS focus, and a missing ECU reading point at different parts of the system.</PageHead>
  <Section title="Follow the symptom"><Table headings={['Symptom', 'Check first']} rows={[
    ['Center DIS is blank; DataView still works', <>Center display enabled/app list, then <code>dis_service</code> and <code>dis_display</code>. The top display has its own service and settings.</>],
    ['Wheel works normally but won’t select DIS items', <>Open Readings or Phone, then double-click MODE. Look for the wheel-mode glyph. Unsupported apps cannot take the wheel; the keyboard journal explains the rejected context.</>],
    ['DIS starts recording but nothing is saved', <>Check <code>hudiy_dataview.service</code>: it owns the named recorder even when the cluster starts it. Check the page’s Log profile and available source values.</>],
    ['One value is missing; other numbers update', 'Inspect that value’s source/status and ECU support. Check estimated/unverified opt-ins. Do not assume that catalog inclusion means your ECU supplies it.'],
    ['Diagnostic values stop while passive values work', 'Check the diagnostics toggle and scanner/flashing ownership. Passive CAN and ECU measuring-group readings have separate acquisition paths.'],
    ['Music works but navigation is blank', 'Check that the projection app has a live route and is actually sending maneuver/distance data. An icon type or active status alone does not establish a usable route.'],
    ['Phone connects but no call page appears', 'Connection is separate from an active call. claim_on_phone controls page display; scroll_wheel_phone_menu controls wheel takeover.'],
  ]}/></Section>
  <Section title="Check services on the Pi"><p>Use an SSH terminal for a compact status check. Failed services usually include a recent error; the journal gives the surrounding context.</p><Command>{'systemctl --no-pager --full status can_handler.service hudiy_status_service.service hudiy_dataview.service hudiy_data_api.service dis_service.service dis_display.service can_keyboard_control.service'}</Command><Table headings={['Service', 'Owns']} rows={[
    [<code>can_handler.service</code>, 'Raw vehicle CAN transport.'],
    [<code>hudiy_status_service.service</code>, 'Named vehicle-value service and provider planning.'],
    [<code>hudiy_dataview.service</code>, 'Touchscreen, named recorder, page/profile store and file portal.'],
    [<code>hudiy_data_api.service</code>, 'Hudiy media, navigation and phone normalization/capture.'],
    [<code>dis_service.service / dis_display.service</code>, 'Center-cluster driver and app rendering.'],
    [<code>can_keyboard_control.service</code>, 'RNS-E/wheel inputs, MODE recognition and wheel ownership.'],
  ]}/><Command>{'journalctl -u can_keyboard_control.service --since "10 minutes ago" --no-pager'}</Command><p>For another symptom, replace that service name with the relevant one above. Wheel logs include MODE double-click recognition, ownership changes and unavailable contexts. The wheel returns to normal actions if the DIS heartbeat disappears.</p></Section>
  <Section title="Check the source, not just the number"><p>DataView exposes <code>http://&lt;Pi-IP&gt;:5003/api/values/status</code> for source inspection. It reports the broker plan and TP2 acquisition status, including requested/achieved rates and inhibition. <code>/api/values/catalog</code> lists values and providers.</p><p>A reading can fall back between matching passive and diagnostic providers. The source metadata tells you which provider supplied it. Stale data keeps its original timestamp; repeated UI refreshes do not make it live.</p></Section>
  <Section title="After a controller operation"><p><strong>Flashing Mode</strong> persists across operations and reboots. It inhibits this project’s normal DIS and diagnostic transmissions, so those views can remain quiet after the operation finishes.</p><p>Check the Hudiy Flashing Mode action and turn it off when the controller workflow permits. It cannot be disabled during an active operation or while an incomplete Haldex flash still requires recovery. A reboot is not a way to clear that state.</p><p>Ignition state matters too: the center-DIS driver waits while ignition/bus activity is off. An active systemd service does not mean it should be drawing in that state.</p><SourceLink source="flasher/traffic.py">Persistent transmission inhibition</SourceLink></Section>
  <Section title="Capture a reproducible problem"><Steps items={[
    ['Write down the small sequence that triggers it', 'Which phone/provider, DIS app, track/call/maneuver and input? Include whether the wheel glyph was present. Repeat once if you can reproduce it.'],
    ['Press Save Logs near the event', 'This collects recent service journals plus current/previous raw API captures in a dated, numbered folder. Capture before rebooting; current service logs are RAM-backed on the installed Pi.'],
    ['Download that capture from File portal → Debug logs', 'Keep the raw files with the event description. API events include fields/presence and normalized results, which can explain a missing route, wrong call state or artwork transition.'],
  ]}/><Note>Raw API captures can include street names, media metadata, contacts and phone numbers. Check what you share when sending a capture.</Note></Section>
  <Settings rows={[
    ['display.center_display.enabled', 'Whether the center-display driver is enabled.'], ['display.phone', 'Separate call-page display and wheel takeover settings.'],
    ['input_mappings.mfsw.double_click_ms', 'MODE/wheel double-click timing.'], ['features.log_saver', 'Service list and history duration saved by Save Logs.'],
  ]}/>
  <SourceLink source="rns-e_can/wheel_controls.py">Wheel context/heartbeat rules</SourceLink><SourceLink source="rns-e_can/save_logs.py">Saved support captures</SourceLink><SourceLink source="install.sh">Installed services</SourceLink>
  <Related links={[[ 'files', 'File portal', 'Saved debug logs, API events and controller reports.' ],['controls','Buttons & wheel','Default normal mappings and DIS gestures.'],['power','Connections & power','Reconnect and shutdown behavior.']]}/>
</>; }

export const HowToPages = {
  'apply-update': ApplyUpdate,
  'build-readings': BuildReadings,
  'record-a-run': RecordRun,
  troubleshooting: Troubleshooting,
};
