import React, { useState } from 'react';
import { DemoImage, Figure, FeatureDemo, Note, PageHead, Related, Section, Settings, SourceLink, Steps, Table, ConfigLaunch } from './ui';
import { WheelExplainer } from './WheelExplainer';
import RnseFaceplate from './RnseFaceplate';
import { NavigationShowcase } from './NavigationShowcase';
import { howToGroup, howToTopics, HowToPages } from './HowToGuides';

export const groups = [
  { id: 'start', title: 'OVERVIEW' },
  howToGroup,
  { id: 'dis', title: 'CLUSTER DISPLAY' },
  { id: 'data', title: 'VEHICLE DATA' },
  { id: 'controls', title: 'CONTROLS & BEHAVIOR' },
  { id: 'setup', title: 'SETUP & TOOLS' },
];
export const topics = [
  { id: 'overview', group: 'start', title: 'What this adds', icon: '⌂', summary: 'Screens and features in this fork', keywords: 'overview capabilities features' },
  { id: 'readings', group: 'dis', title: 'Custom readings', icon: '▦', summary: 'Build eight-slot DIS pages and link recordings', keywords: 'car_info values units precision icons page editor slots white red logging' },
  { id: 'navigation', group: 'dis', title: 'Navigation', icon: '↱', summary: 'Turn guidance and automatic switching', keywords: 'directions maneuver distance approach bar stock bitmap icons' },
  { id: 'media', group: 'dis', title: 'Music & album art', icon: '♫', summary: 'Now playing, cover art and track-triggered GIFs', keywords: 'music media coverart playback scrolling artist album eggs gif' },
  { id: 'phone', group: 'dis', title: 'Phone calls', icon: '☎', summary: 'Caller details, wheel selection and call takeover', keywords: 'phone call accept reject caller end wheel mode takeover' },
  { id: 'acceleration', group: 'dis', title: 'Acceleration timing', icon: '◴', summary: 'Speed-range and distance-run timers', keywords: '0-60 timer quarter mile tolerance speed reset' },
  { id: 'top-display', group: 'dis', title: 'Top display', icon: '☰', summary: 'Independent two-line content, priority and formatting', keywords: 'top lines strip phone navigation media metadata scrolling priority format' },
  { id: 'dataview', group: 'data', title: 'Vehicle dashboards', icon: '◴', summary: 'Read the Engine, Transmission and AWD screens', keywords: 'boost fuel pressure knock timing clutch selector Haldex Stock Perf Comp torque smoothing' },
  { id: 'recordings', group: 'data', title: 'Record & review', icon: '≋', summary: 'Profiles, graphs, events, markers and CSV', keywords: 'data logs recording traces cursor value picker export' },
  { id: 'diagnostics', group: 'data', title: 'Faults & measuring groups', icon: '⊞', summary: 'Read/clear DTCs and inspect ECU measuring groups', keywords: 'scanner VCDS fault codes module picker TP2 freeze frame' },
  { id: 'controllers', group: 'data', title: 'Controller tools', icon: '⚙', summary: 'Haldex, EPS and exhaust firmware/readout workflows', keywords: 'flashing flash update steering dataset EEPROM Gen4 valve open close recovery firmware unconfirmed' },
  { id: 'controls', group: 'controls', title: 'Buttons & wheel', icon: '⊕', summary: 'Normal mappings, DIS focus and phone takeover', keywords: 'MODE double click stalk rocker MMI steering long press volume' },
  { id: 'power', group: 'controls', title: 'Connections & power', icon: '⏻', summary: 'Reconnect, day/night, time sync and shutdown', keywords: 'ignition Bluetooth Android Auto CarPlay radio GPIO listen only source unlock wake' },
  { id: 'setup', group: 'setup', title: 'Install & update', icon: '↓', summary: 'Hardware, updater and service checks', keywords: 'Pi Raspberry installation testing release beta backup' },
  { id: 'configuration', group: 'setup', title: 'Configuration helper', icon: '⚙', summary: 'Load, edit and export the selected branch config', keywords: 'repo branch config.json settings import download' },
  { id: 'files', group: 'data', title: 'File portal', icon: '▤', summary: 'Firmware uploads, drive recordings and debug-log downloads', keywords: 'binary bin file upload PIN ZIP archive folders CSV download Save Logs API readout' },
  { id: 'tools', group: 'setup', title: 'Developer tools', icon: '↗', summary: 'Artwork, text, themes, emulation and CAN tools', keywords: 'AUDSCII bitmap GIF image tester DHU bench catalog measuring inspector' },
  ...howToTopics,
];

function Overview() {
  const [demo, setDemo] = useState('readings');
  const demos = {
    readings: { title: 'Custom readings', src: 'dis-readings-controls.gif', description: 'Eight chosen values, multiple pages, and recording controls on the steering wheel.', link: 'readings' },
    navigation: { title: 'Navigation', src: 'dis-navigation-approach.gif', description: 'Maneuver artwork, distance, street text and a live approach bar.', link: 'navigation' },
    media: { title: 'Now playing', src: 'dis-media-scroll.gif', description: 'Track metadata, playback progress and scrolling text.', link: 'media' },
    phone: { title: 'Calls', src: 'dis-phone.png', description: 'Caller details and Accept, Reject or End Call controls.', link: 'phone' },
  };
  const shown = demos[demo];
  return <>
    <div className="hero overview-hero"><div><div className="eyebrow">DSPARKS156X / RNS-E-HUDIY</div><h1>RNS-E Hudiy<br/>features & setup</h1><p className="lead">This fork connects Hudiy, the instrument cluster, steering-wheel controls and vehicle diagnostics. Use this guide to set up DIS pages, record vehicle data, read faults and work with supported controllers.</p><div className="hero-actions"><a className="primary-button" href="#readings">Build a DIS page →</a><a className="text-button" href="#setup">Install & update ↗</a></div></div><div className="cluster-showcase"><div className="showcase-top"><span>ON THE DIS</span><span>128 × 96</span></div><DemoImage key={shown.src} pixel src={shown.src} alt={shown.description}/><div className="demo-tabs" aria-label="DIS examples">{Object.entries(demos).map(([id, value]) => <button key={id} onClick={() => setDemo(id)} aria-pressed={id === demo}>{value.title}</button>)}</div><p className="showcase-description">{shown.description}</p><a className="source-link" href={`#${shown.link}`}>How this works →</a></div></div>
    <Section title="The main features">
      <div className="feature-pair">
        <a className="feature-card sage" href="#readings"><div className="card-heading"><span>CLUSTER DISPLAY</span><span className="arrow">↗</span></div><h3>Custom DIS pages</h3><p>Build eight-slot pages with your choice of values, units, icons and number formatting. Link a page to a recording profile, then start, stop or mark the same session from the DIS.</p><span className="card-cta">Build and use a page →</span></a>
        <a className="feature-card sand" href="#recordings"><div className="card-heading"><span>DATA & LOGS</span><span className="arrow">↗</span></div><h3>Recording & review</h3><p>Pick values from the catalog, add markers while recording, inspect unit-grouped graphs and recorded events, then export the complete CSV.</p><span className="card-cta">Profiles, graphs and export →</span></a>
      </div>
      <FeatureDemo src="dataview-engine.gif" pixel={false} caption="Engine dashboard: airflow and boost, ignition timing and cylinder retard, fuel system and temperatures." title="Engine, Transmission and AWD dashboards"><p>Compare actual versus requested boost and rail pressure, check clutch pressures and selector travel, or view Haldex telemetry and mode controls. Each dashboard has a guide to its gauges, values and status indicators.</p><a className="text-button inline-link" href="#dataview">Read the dashboards →</a></FeatureDemo>
    </Section>
    <div className="feature-index">
      {[
        ['navigation', 'Navigation', 'Maneuver artwork, distance and an approach bar. Turn guidance can switch in near the maneuver.'],
        ['media', 'Music & album art', 'Track metadata, scrolling text, brief album covers and track-triggered GIFs.'],
        ['phone', 'Phone calls', 'Caller details and wheel-controlled Accept, Reject and End Call actions.'],
        ['diagnostics', 'Fault codes & measuring groups', 'Read or clear supported faults, inspect freeze-frame data, and choose ECU measuring groups on the touchscreen.'],
        ['files', 'File portal: uploads & logs', 'Upload validated controller binaries from your phone or computer. Download drive CSVs, debug logs and controller readouts, individually or as ZIPs.'],
        ['controllers', 'Haldex, steering & exhaust tools', 'Controller identification, validated firmware workflows, readouts, and exhaust-valve commands.'],
        ['controls', 'Wheel, buttons & vehicle behavior', 'Use the original controls, manage DIS ownership, and configure reconnect, day/night, clock and power behavior.'],
      ].map(([id, title, text]) => <a href={`#${id}`} key={id}><h3>{title}<span>↗</span></h3><p>{text}</p></a>)}
    </div>
    <Related links={[
      ['configuration', 'Configuration helper', 'Defaults to your repo / testing. Open loads the latest branch config.'],
      ['files', 'Get files off the Pi', 'Download logs and readouts, or upload validated firmware.'],
      ['tools', 'Developer tools', 'Bitmap, text and theme helpers; image testing and emulation.'],
    ]}/>
  </>;
}

function Readings() { return <>
  <PageHead location="CLUSTER DISPLAY / READINGS" title="Custom DIS readings">The white/native cluster supports pages with eight chosen readings, individual formatting and a linked recording profile. The red cluster keeps its older five-line Car Info display.</PageHead>
  <Section title="Readings and wheel controls"><p>Four pairs of readings fill the center area. The header holds the page name and recording actions. Use the examples below to see what each selection means.</p><WheelExplainer mode="readings"/></Section>
  <Section title="Build a page in DataView">
    <Figure src="dataview-dis-editor.jpg" caption="Data & Logs → DIS pages. Edit each slot, choose a linked log profile, then Apply the page changes."/>
    <Steps items={[
      ['Open Data & Logs → DIS pages', 'Select an existing page or use + to add one. The grid labels match the cluster: 1L/1R through 4L/4R.'],
      ['Tap a slot and choose a reading', 'Browse the catalog by system and function, or search for the value. Provider information shows where it comes from and whether it is estimated or unverified.'],
      ['Set the presentation', 'Choose source or converted units, 0–3 decimal places, fixed or proportional font, and an automatic or manually selected pixel icon. Provider opt-ins belong to the slot.'],
      ['Finish the slot, then Apply', 'Done returns to the page draft. Apply saves all page edits. If you only press Done, you have not saved the page yet.'],
    ]}/>
    <p><strong>Page settings</strong> renames, duplicates and moves pages earlier or later. The <strong>Log:</strong> dropdown links the page to the recording profile its play button should start.</p>
  </Section>
  <Section title="How readings and recordings fit together"><p>The DIS and touchscreen control <strong>one session</strong>. Start on either screen, mark on the other, and review it in DataView. The DataView service must be running even when you start from the wheel.</p><p>Each slot chooses its own units. The config helper’s navigation/legacy unit settings do not override these pages. Missing or stale readings become unavailable rather than keeping an old number on screen.</p></Section>
  <Section title="Red-cluster Car Info"><FeatureDemo src="dis-car-info-legacy.png" caption="The older red/low-resolution screen: boost, airflow, ignition timing, oil and coolant." title="Five fixed readings"><p>The normal/red layout retains the existing Car Info page instead of the eight-slot page editor and recording header.</p><p>Match <code>display.center_display.high_resolution</code> to the cluster you have. The screenshots above show the white/native layout; this one shows the older font and five-row format.</p></FeatureDemo></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Include car_info to make the readings app available. Its list position determines the stalk cycle order.'],
    ['display.center_display.high_resolution', 'The native/white layout uses eight slots. The normal/red layout retains the older five-line Car Info screen. Match your cluster.'],
    ['data_logs.directory', 'Stores shared page/profile configuration and named recording sessions. The default is ~/logs/data-logs.'],
  ]}/>
  <Related links={[[ 'recordings', 'Recording profiles & review', 'Choose what to record, inspect graphs and export CSV.' ],['controls','Wheel ownership','Manual control, phone takeover and double-click timing.']]}/>
</>; }

function Navigation() { return <>
  <PageHead location="CLUSTER DISPLAY / NAVIGATION" title="Navigation on the DIS">Turn instructions from Hudiy appear in the cluster with street text and a maneuver approach bar. You can select navigation yourself or let it interrupt another page near a turn.</PageHead>
  <Section title="Stock icons & bitmap artwork"><NavigationShowcase/><p>The street line scrolls when the instruction does not fit. Distance formatting follows your navigation units. The instructions available depend on what the Hudiy navigation source sends.</p><p>On the native white DIS, <code>display.center_display.navigation.icon_style</code> selects <code>stock</code> or <code>bitmap</code>. If that optional key is absent, the renderer uses bitmap unless the older renderer setting selects stock. The red display uses its legacy layout.</p></Section>
  <Section title="Automatic switching, step by step"><Steps items={[
    ['A maneuver arrives or changes', 'Navigation gets a five-second preview. This lets you see the next instruction even while another app is selected.'],
    ['You reach the approach distance', 'Navigation stays in front. The current config starts this at 500 m from the maneuver.'],
    ['The next maneuver is farther away', 'Once distance retreats beyond the return threshold—1000 m in the current config—the approach interruption resets.'],
    ['You choose another page manually', 'That maneuver’s approach switching is suppressed until the maneuver changes or distance retreats. The page does not immediately yank you back.'],
  ]}/><p>Bringing up navigation near a maneuver and claiming the cluster for the whole route are separate settings.</p></Section>
  <Settings rows={[
    ['display.center_display.navigation.auto_switch', 'Enable maneuver previews and approach interruptions.'],
    ['display.center_display.navigation.auto_switch_approach_threshold', 'Distance in meters at which navigation stays in front.'],
    ['display.center_display.navigation.auto_switch_return_threshold', 'Keep this larger than the approach threshold to avoid switching around one boundary.'],
    ['display.center_display.navigation.approach_bar_max_distance', 'Distance range for the bar itself; independent of page switching. The current config uses 300 m.'],
    ['display.center_display.navigation.claim_on_nav', 'Claim the center display while a route is active and release it when the route ends.'],
    ['display.units.speed', 'Imperial, metric or the car setting for navigation distance and speed-based features.'],
  ]}/>
  <Related links={[[ 'top-display', 'Top display', 'Keep turn information above another center app.' ],['controls','Change apps','Stalk cycling and the steering wheel.']]}/>
</>; }

function Media() { return <>
  <PageHead location="CLUSTER DISPLAY / MUSIC" title="Music & album art">Show track metadata and playback progress on the DIS, bring up the album cover when a song changes, or play a GIF for a matching track.</PageHead>
  <FeatureDemo src="dis-media-scroll.gif" caption="Track, artist and album text scroll to fit; playback position and duration stay on the media page." title="Now playing"><p>The page uses the metadata Hudiy provides: title, artist, album, playback position and duration. Long lines scroll using your shared DIS text settings.</p><p>When the center already shows media, the top display can use an alternate first-line format—for example the source instead of repeating the song title.</p></FeatureDemo>
  <FeatureDemo src="dis-cover-art.png" caption="Cover art converted to the cluster’s monochrome image area. This sample uses the balanced preset." title="Album cover art"><p>With <code>brief</code> enabled, a track change shows the cover for five seconds while Media is selected. Add <code>coverart</code> to the app list if you want it as a page you can cycle to.</p><p>Choose <strong>legacy</strong> for your saved processing arguments, <strong>balanced</strong> for ordered dithering, <strong>photo</strong> for error diffusion or <strong>text</strong> for a crisp threshold.</p></FeatureDemo>
  <Section title="Track-triggered GIFs"><p><code>dis_client/eggs.json</code> maps artist/title/album patterns to local GIFs. A matching track while Media is selected queues the animation behind any brief cover-art display.</p><p>Choose the regular expression, GIF path, loop count and processing settings there. The bundled matches include Polish Cow, TRON: Legacy and Never Gonna Give You Up. The cluster can, apparently, rickroll you.</p></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Include media or coverart in the center apps you can cycle through.'],
    ['display.center_display.coverart', 'Brief display, processing preset/arguments, draw order and changed-tile behavior.'],
    ['display.text_scrolling', 'Scroll speed, pauses at each end, looping gap and per-line start offset.'],
    ['display.top_display', 'Media line formats and the alternate first line when the center shows Media.'],
  ]}/>
  <Related links={[[ 'controls', 'Media controls', 'Default wheel and faceplate playback actions.' ],['top-display','Top display','Keep track details above another center app.'],['phone','Phone calls','Answer, reject or end a call with the wheel.']]}/>
</>; }

function Phone() { return <>
  <PageHead location="CLUSTER DISPLAY / PHONE" title="Phone calls">Caller details and call actions appear on the DIS. The wheel can select Accept or Reject for an incoming call, then End Call while the call is active.</PageHead>
  <Section title="Wheel selection and the mode icon"><p>The circled wheel icon shows when call actions have the navigation wheel. The highlighted row is what a click will do; rotation changes the selection.</p><WheelExplainer mode="phone"/><p>Caller details come from Hudiy. Phone controls also work when the call is shown only on the top display. A connected phone with no live call does not bring up the call page.</p></Section>
  <Section title="Two separate phone choices"><Table headings={['Option', 'Behavior']} rows={[
    ['Claim the center display for calls', 'claim_on_phone can resume or claim the center while a call is active, then release an automatically claimed session when it ends.'],
    ['Give the phone the wheel automatically', 'scroll_wheel_phone_menu gives visible phone controls wheel ownership. Manual readings control takes priority.'],
    ['Keep normal wheel actions during a call', 'Double-click MODE to override automatic takeover for that call.'],
  ]}/><p>Within an active center session, call activity overlays the Phone page. Claiming the center and giving the phone the wheel are separate choices.</p></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Include phone for a center call page.'],
    ['display.phone.claim_on_phone', 'Resume or claim the center display for a call.'],
    ['display.phone.scroll_wheel_phone_menu', 'Automatic call wheel takeover.'],
    ['display.top_display', 'Phone priority and caller/state formatting on the top lines.'],
  ]}/>
  <Related links={[[ 'controls', 'Wheel controls', 'Select call actions and return to normal mappings.' ],['top-display','Top display','Configure the two lines separately from the center app.']]}/>
</>; }

function Acceleration() { return <>
  <PageHead location="CLUSTER DISPLAY / ACCELERATION" title="Acceleration timing">The acceleration app measures configured speed ranges and distance runs from CAN speed. Choose the four rows and how the timers reset.</PageHead>
  <FeatureDemo src="dis-acceleration-run.gif" caption="Four configured rows: 0–60, 0–30, 40–70 mph and live speed, during a simulated acceleration run." title="Four rows, your choice"><p>A row can time a speed range, time a distance, or just show speed. Timers start and finish when the CAN speed crosses the chosen thresholds; crossings are interpolated between samples.</p><p>The optional ± figure reports sample-time tolerance. These are CAN-derived timings, not GPS instrumentation.</p></FeatureDemo>
  <Section title="Row formats"><Table headings={['Enter', 'What it does']} rows={[
    [<code>0-60</code>, 'Time from 0 to 60 in your selected speed units. Other ranges such as 40-70 work the same way.'],
    [<code>1/4</code>, 'Time a quarter mile with imperial units or a quarter kilometer with metric units. Decimal distances below 10 work too.'],
    [<code>1000</code>, 'Larger numeric distances use feet in imperial mode or meters in metric mode.'],
    [<code>speed</code>, 'Show live speed instead of a timer.'],
  ]}/><p>Stopped auto-reset and its delay are configurable. Cycling away and back with the stalk resets the timers.</p></Section>
  <Settings rows={[
    ['display.center_display.acceleration_test', 'The four timing/live-speed rows, stopped reset behavior and sample-time uncertainty display.'],
    ['display.units.speed', 'mph/miles/feet or km/h/km/meters; car follows the vehicle setting.'],
  ]}/>
  <Related links={[[ 'controls', 'Stalk & wheel controls', 'Cycle to the acceleration app and return to other pages.' ]]}/>
</>; }

function TopDisplay() { return <>
  <PageHead location="CLUSTER DISPLAY / TOP DISPLAY" title="Top display">The two lines above the center area show phone, navigation or media content independently of the selected center app. They have their own priority order and line formats.</PageHead>
  <FeatureDemo src="dis-top-media.gif" caption="The top strip on its own: eight-character windows scroll track and artist independently." title="Content above the center page"><p>The strip keeps its own content while you use another center app. For example, track and artist can stay visible while the center shows vehicle readings.</p><p>Long text scrolls within each line. Configure its speed, end pauses, looping gap and start offset using the shared text-scrolling settings.</p></FeatureDemo>
  <Section title="Choose which app takes priority"><p>Top-display priority is independent of the center app list. The first app with active content wins; the example order is <strong>Phone → Navigation → Media</strong>.</p><p>Change <code>display.top_display.applist</code> to set that order. Each selected app supplies its own two line formats.</p></Section>
  <Section title="Choose each line’s content"><Table headings={['App', 'Line-format fields']} rows={[
    ['Media', 'title, artist, album, source. An alternate first line is used when the center already shows Media.'],
    ['Navigation', 'description, maneuver, distance.'],
    ['Phone', 'caller, state, name, connection, battery, signal, as supplied by Hudiy.'],
  ]}/><p>Combine fields with a hyphen in the format string, such as <code>title-artist</code>. You choose each line’s content in the config helper.</p></Section>
  <Settings rows={[
    ['display.top_display.applist', 'Priority of active phone/nav/media content on the top lines.'],
    ['display.top_display', 'Fields shown on each line, including the alternate first media line.'],
    ['display.text_scrolling', 'Shared scrolling speed, pauses, looping gap and per-line start offset.'],
  ]}/>
  <Related links={[[ 'media', 'Music & album art', 'Center media pages and cover-art display.' ],['phone','Phone calls','Call information and wheel actions.'],['navigation','Navigation','Center maneuver guidance and automatic switching.']]}/>
</>; }

function Dashboards() {
  const [tab, setTab] = useState('engine');
  const screens = {
    engine: { title: 'Engine', src: 'dataview-engine.gif', caption: 'Air/boost on the left, RPM and ignition timing in the center, fuel system on the right, temperatures below.' },
    transmission: { title: 'Transmission', src: 'dataview-transmission.jpg', caption: 'Clutch pressures and supporting values on the left; four selector-travel bars on the right.' },
    awd: { title: 'AWD', src: 'dataview-awd.jpg', caption: 'Haldex readings, requested versus active mode, and the separate Drive Logger controls.' },
  };
  const shown = screens[tab];
  return <>
    <PageHead location="VEHICLE DATA / DATAVIEW" title="Vehicle dashboards">DataView has Engine, Transmission and AWD dashboards, alongside Data & Logs and Diagnostics. Tap the tabs or swipe between them.</PageHead>
    <div className="screen-tabs" aria-label="Dashboard guides">{Object.entries(screens).map(([id, screen]) => <button key={id} aria-pressed={id === tab} onClick={() => setTab(id)}>{screen.title}</button>)}</div>
    <Figure key={shown.src} src={shown.src} caption={shown.caption}/>
    {tab === 'engine' && <Section title="Read the Engine screen"><Table headings={['Area', 'What you’re looking at']} rows={[
      ['Air & boost', 'Mass airflow in g/s. Boost shows actual absolute pressure in mbar, with a separate specified-pressure marker for comparison.'],
      ['RPM & ignition', 'Engine speed and timing advance. Four retard bars show timing pull for each cylinder.'],
      ['Fuel', 'Actual rail pressure, specified pressure, pump duty and injection duration.'],
      ['Temperatures', 'Oil, ambient, intake air and coolant temperatures.'],
    ]}/><p>Boost is <strong>absolute</strong> pressure here. It includes atmospheric pressure, so do not read it as gauge boost above atmosphere.</p></Section>}
    {tab === 'transmission' && <Section title="Read the Transmission screen"><Table headings={['Area', 'What you’re looking at']} rows={[
      ['Clutches', 'Compare the two actual-pressure gauges with shaft speed, requested torque and valve current for each clutch.'],
      ['Selector travel', 'Four bars correspond to the 1/3, 2/4, 5/N and 6/R selectors. Values report selector travel.'],
      ['Status row', 'Fluid, module and clutch-oil temperature plus transmission status.'],
    ]}/><p>The available readings depend on the fitted transmission controller and the groups it supplies.</p></Section>}
    {tab === 'awd' && <Section title="Read the AWD screen"><Table headings={['Area', 'What you’re looking at']} rows={[
      ['Pressure & torque', 'Haldex oil pressure and estimated torque. The torque estimate is identified as estimated.'],
      ['Valve & control', 'N273 valve opening/current, commanded torque and slip-control torque.'],
      ['Mode selection', 'Stock / Perf / Comp request the corresponding firmware mode. Check Active mode and status; selecting a button alone is not controller acknowledgement.'],
      ['Safety & status', 'The ARMED badge shows the safety-token state. Other values include oil/plate temperature, supply voltage and vehicle/slip/operating modes.'],
      ['Drive Logger', 'The older Haldex-fused/Raw CAN logger, with its own recording and marker controls.'],
    ]}/><p><code>haldex.default_mode</code> can choose the startup mode. Set it to <code>null</code> to restore the saved selection.</p><Note>Custom mode control and telemetry need compatible Haldex firmware. Stock/Perf/Comp behavior is defined by the firmware installed on your controller.</Note></Section>}
    <Section title="Smoothing and missing readings"><p>The <strong>~</strong> button toggles smoothing. It changes how values move on screen; it does not make the ECU deliver samples faster.</p><p>Readings carry source, freshness and quality. Missing, invalid or stale values display as unavailable. Catalog entries describe supported mappings; they do not guarantee that every controller provides them.</p></Section>
    <Related links={[[ 'recordings', 'Record these values', 'Choose a profile, add markers and inspect the result.' ],['controllers','Haldex controller tools','Firmware, identification and readout workflows.']]}/>
  </>;
}

function Recordings() { return <>
  <PageHead location="VEHICLE DATA / DATA & LOGS" title="Record, review & export">Record only the values you choose. Add markers during the drive, inspect the result on the touchscreen, or export the entire recording as CSV.</PageHead>
  <Figure src="dataview-record.jpg" caption="Record: select a profile, choose values, start recording and add markers without leaving the screen."/>
  <Section title="Make a recording profile"><Steps items={[
    ['Open Data & Logs → Record', 'Choose an existing profile from the dropdown. + creates a profile using the current selection’s values, so it is useful for making a variation. Profile settings names it and sets estimated/unverified provider opt-ins.'],
    ['Choose values', 'Browse system → function/group, or search across all systems. Selected shows only the values already chosen. Read provider labels when picking an estimated or unverified value.'],
    ['Start and add markers', 'Start records the selected profile. Mark adds a timestamped event. Recording continues even if you switch to another dashboard tab.'],
    ['Stop & save or Stop & review', 'Stop & save leaves you on Record. Stop & review saves the session and opens its recent section.'],
  ]}/></Section>
  <Figure src="dataview-value-picker.jpg" caption="The value picker groups available readings by system and function. Search spans the catalog; Selected narrows it to your chosen values."/>
  <Section title="Review a session"><Figure src="dataview-review.jpg" caption="Review: unit-grouped traces, inspected values, marker jumps and time-window controls."/><Table headings={['Control', 'Use it for']} rows={[
    ['Traces', 'Choose which numeric values to graph. Values are grouped by the units recorded in their samples.'],
    ['Tap a graph', 'Place a cursor and inspect values at that time. + / − zoom around the cursor.'],
    ['Earlier / Later', 'Move the visible time window through the recording.'],
    ['Last 10s / Last 30s / Full log', 'Jump to a recent section or show the full duration.'],
    ['Marker list', 'Jump directly to a marked event.'],
    ['Events', 'Search nonnumeric readings and unavailable/error status changes.'],
    ['CSV', 'Export the full session, even when the on-screen review reaches its sample limit.'],
  ]}/><p>Stale and invalid samples produce gaps. They do not become a flat line that looks like a steady measurement.</p></Section>
  <Section title="What the saved session contains"><p>Starting a session captures its profile and catalog metadata. Later profile edits do not rewrite an old recording. The live footer reports dropped rows: those rows were not saved. Restarting the DataView service does not resume a running session.</p><a className="text-button inline-link" href="#record-a-run">Choose values and interpret the recording →</a></Section>
  <Section title="Start it from the DIS"><p>Choose a page’s <strong>Log:</strong> profile in the DIS editor. The cluster play/stop/flag controls operate this same session. DataView’s service stays responsible for the recorder, independently of whichever tab is visible.</p><a className="text-button inline-link" href="#build-readings">Build a readings page →</a></Section>
  <Section title="Two recorders, different jobs"><Table headings={['Recorder', 'Where / what it records']} rows={[
    ['Data & Logs', 'Chosen named values and shared DIS profiles. Review graphs/events and export the complete recording. Stored under data_logs.directory.'],
    ['AWD Drive Logger', 'Older Haldex fused and Raw CAN profiles for engineering/debugging. Understeer, Oversteer and Launch markers. Uses data_logger and its separate directory.'],
  ]}/></Section>
  <Related links={[[ 'readings', 'Custom DIS readings', 'Build pages and link their recording profile.' ],['files','Files & support logs','Get raw logs, service captures and readouts off the Pi.']]}/>
</>; }

function Diagnostics() { return <>
  <PageHead location="VEHICLE DATA / DIAGNOSTICS" title="Fault codes & measuring groups">Choose an ECU module, read or clear supported fault codes, and view up to three selected measuring groups.</PageHead>
  <Figure src="dataview-diagnostics.jpg" caption="Diagnostics module picker. Supported controller workflows open from their module; the exhaust controller has its own tile."/>
  <Section title="Read fault codes"><Steps items={[
    ['Choose a module', 'Open Diagnostics and tap Engine, Auto Trans, AWD or another listed module. This is a module picker, not proof that every listed ECU supports every operation.'],
    ['Read DTCs and wait for the response', 'The initial “No fault codes found” label appears before a read has completed too; it is not evidence of a clean ECU. The returned fault list shows decimal/hex code and decoded status. Freeze-frame fields are decoded when supported; otherwise the raw bytes remain visible.'],
    ['Clear DTCs when appropriate', 'The clear operation is separate from reading. Check the module’s response and read again to see its current state.'],
  ]}/><p>Engine is the most established path. Support on other controllers varies.</p></Section>
  <Section title="Inspect measuring groups"><Figure src="dataview-diagnostics-engine.jpg" caption="Engine measuring groups 3, 20 and 115: three independent selectors, returned fields and units. Values and empty fault list are synthetic."/><Steps items={[
    ['Tap Grp 1, Grp 2 or Grp 3', 'Enter a group number with the keypad. The selected module supplies the values.'],
    ['Compare the returned fields', 'The screen shows up to three groups at once, with four fields per group. Group numbers and field meanings depend on the controller.'],
    ['Free a selector or switch modules', 'Clear a group number in the keypad to release that selector. Group selections are remembered per module while the UI is running.'],
  ]}/></Section>
  <Section title="Engine group examples"><Table headings={['Group', 'What to compare']} rows={[
    ['3', 'Engine speed, mass air flow and ignition timing.'],
    ['20', 'Timing retard for the four cylinders.'],
    ['115', 'Requested versus actual absolute boost pressure.'],
  ]}/><p>These are catalog examples for supported engine ECUs. Read the returned labels and units rather than assuming a group means the same thing on every controller.</p></Section>
  <Section title="Use another scanner"><p>Disable diagnostics using the Hudiy diagnostic action/toggle before connecting VCDS or another scanner. This stops the project’s diagnostic activity so the other tool can use the link.</p><p>Passive CAN readings can still be available when diagnostics is off. A CAN-derived temperature and an ECU measuring-group value do not necessarily come from the same source.</p></Section>
  <Related links={[[ 'controllers', 'Controller tools', 'Haldex Gen4, PQ EPS and exhaust workflows.' ],['dataview','Dashboards','Normal live Engine, Transmission and AWD views.']]}/>
</>; }

function Controllers() { return <>
  <PageHead location="VEHICLE DATA / CONTROLLER TOOLS" title="Haldex, EPS & exhaust tools">Controller identification, firmware validation, selected-region transfers and readouts are separate workflows from the normal live dashboards.</PageHead>
  <div className="page-summary"><span>On this page</span><a href="#controllers" onClick={e => { e.preventDefault(); document.getElementById('haldex-tools').scrollIntoView(); }}>Haldex Gen4</a><a href="#controllers" onClick={e => { e.preventDefault(); document.getElementById('eps-tools').scrollIntoView(); }}>PQ EPS</a><a href="#controllers" onClick={e => { e.preventDefault(); document.getElementById('exhaust-tools').scrollIntoView(); }}>Exhaust valve</a></div>
  <Section title="Haldex Gen4" id="haldex-tools"><p><strong>Open:</strong> Diagnostics → AWD → Flash Controller. The Stock/Perf/Comp mode buttons are on the normal AWD dashboard; firmware operations are here.</p><Figure src="dataview-controller.jpg" caption="The controller panel separates identification, sector selection, firmware selection and the read/flash actions. Sample identity; no transfer shown."/><Steps items={[
    ['Upload and refresh', 'Put a validated image on the Pi through the file portal, then refresh the firmware list in the controller tool.'],
    ['Query Controller', 'Read controller identification before selecting a compatible image and sectors. Query results influence the default region selection.'],
    ['Choose the transfer or readout coverage', 'Selected sectors determine which firmware areas are written or read. Supported 320 KiB images are patched and their checksums repaired by the workflow.'],
    ['Hold to Flash, or read the selected sectors', 'Writing shows progress and recovery status. Readouts can be cancelled with two taps; their reports describe which sectors were captured.'],
  ]}/><p>A Haldex readout is not automatically a full backup: unread addresses contain <code>FF</code> padding. Keep the coverage report with the image.</p><SourceLink source="references/HALDEX_READOUT.md">Readout details</SourceLink></Section>
  <Section title="Read Haldex firmware without uploading anything"><Steps items={[
    ['Query the controller', 'Open Diagnostics → AWD → Flash Controller and use Query Controller. No input firmware file is needed for a readout.'],
    ['Select the sectors to capture', 'Choose the coverage, then Read Controller firmware. A cancelled or failed operation can still produce a report; that does not mean the entire image was captured.'],
    ['Keep the BIN and report together', 'The report records coverage and checksum results. Unread addresses contain FF padding, so compare its coverage before calling the image a full backup. Download both from the file portal.'],
    ['Exit Flashing Mode when permitted', 'Readout enters the same persistent Flashing Mode as other controller operations. Turn it off through Hudiy after completion when the workflow permits.'],
  ]}/></Section>
  <Section title="PQ EPS steering" id="eps-tools"><p><strong>Open:</strong> Diagnostics → Steering Assist → Flash Controller.</p><Figure src="dataview-eps.jpg" caption="PQ EPS with a sample 4 KiB dataset. The input locks the region to the steering dataset; live revision determines whether the action is allowed."/><Table headings={['Input / operation', 'Purpose']} rows={[
    ['384 KiB CPU-linear image', 'Full supported EPS firmware image.'],
    ['Exact 4 KiB steering dataset', 'Steering dataset transfer, distinct from a full firmware update.'],
    ['Region selection', 'Full firmware, configuration or steering dataset. Partial regions require a live reported revision of 3000 or newer.'],
    ['Read EPS EEPROM (1 KiB)', 'EEPROM readout. This is not a dump of the main firmware.'],
  ]}/><p>Upload a supported file, refresh the list, query the controller, choose the permitted region, then use the hold-to-flash workflow.</p></Section>
  <Section title="Exhaust valve" id="exhaust-tools"><p><strong>Open:</strong> the exhaust-controller tile in Diagnostics, or the configured Hudiy bar control for the valve action.</p><Figure src="dataview-exhaust.jpg" caption="Exhaust controller: the last requested target is explicitly unconfirmed; firmware controls are separate from Open/Close."/><p><strong>Open / Close</strong> sends the requested target. The controller stores its own target; the Pi remembers its last sent intent. There is no return route for physical position or transfer acknowledgement, so status remains <strong>sent / unconfirmed</strong>.</p><Steps items={[
    ['Upload a complete bundle', 'Use a ZIP or separate manifest plus both native slot images. The workflow checks manifest, CRC and vector information.'],
    ['Refresh and Validate only', 'Confirm that the chosen bundle passes validation before entering the update workflow.'],
    ['Update firmware, then confirm the update', 'The panel presents the explicit firmware update confirmation and reports the sent/unconfirmed transfer state.'],
  ]}/><SourceLink source="flasher/EXHAUST_VALVE.md">Bundle and command details</SourceLink></Section>
  <Section title="Flashing Mode stays on afterward"><p>Controller operations enable Flashing Mode automatically. It inhibits application CAN transmitters while passive reception and logs stay available.</p><p>The mode persists across restarts and reboots, and it remains on after an operation. Use <strong>Hudiy app menu → Flashing Mode</strong> to switch it off manually when finished. Haldex/EPS operations require verified application boot; active transfers and unresolved recovery prevent disabling it.</p><Note>These workflows have offline tests; recoverable hardware-bench acceptance remains outstanding. Image validation and a successful simulated transfer do not establish physical-controller compatibility.</Note><SourceLink source="references/FLASHING_MODE.md">Flashing Mode and recovery</SourceLink></Section>
  <Related links={[[ 'files', 'Upload firmware & download readouts', 'Use the Pi’s file portal.' ],['dataview','AWD dashboard','Live telemetry and requested/active Haldex modes.']]}/>
</>; }

function Controls() { return <>
  <PageHead location="CONTROLS & BEHAVIOR / INPUTS" title="Buttons & wheel controls">The original buttons control Hudiy through configurable keyboard mappings. These are this fork’s bundled defaults, including what the wheel does before you give it to the DIS.</PageHead>
  <Section title="Normal steering-wheel controls"><Table headings={['Control', 'Press or rotate', 'Hold']} rows={[
    ['Navigation wheel', 'Up: previous media · Down: next media', '—'],
    ['Navigation wheel click', 'Play / pause', 'Play / pause'],
    ['MODE', 'Select / confirm', 'Go back'],
    ['Voice / PTT', 'Projection voice assistant', 'Hudiy home'],
    ['Volume wheel and click', 'Car’s volume controls; no added Pi action', 'No added Pi action'],
  ]}/></Section>
  <Section title="RNS-E faceplate"><p>Select a button or knob to see its press, hold and extended-hold actions. The display here is illustrative; selecting a control only changes its description.</p><RnseFaceplate/></Section>
  <Section title="Give the navigation wheel to the DIS"><p>Use the <strong>stalk rocker</strong> to cycle the configured center apps. On a native readings page or Phone screen, <strong>double-click MODE</strong> to give the navigation wheel to that screen. The little wheel icon confirms ownership.</p><Table headings={['While DIS owns the wheel', 'Result']} rows={[
    ['Rotate the navigation wheel', 'Move between header actions, browse readings pages, or select Accept / Reject.'],
    ['Click the navigation wheel', 'Use the selected action.'],
    ['Double-click the navigation wheel', 'Cancel a readings page change, or return selection to the page name / Accept. Wheel ownership stays with the DIS.'],
    ['Double-click MODE', 'Restore the normal wheel mappings.'],
    ['Change center apps with the stalk', 'Release manual DIS wheel control.'],
  ]}/><p>The volume controls keep their normal behavior. If the DIS service heartbeat disappears, the navigation wheel returns to normal mappings.</p></Section>
  <Section title="Phone takeover"><p>Automatic call control is a separate setting from showing the call on the center display. It can give the phone the wheel even with top-only call information.</p><p>Explicit readings control takes priority. Double-click MODE to keep normal wheel actions for the current call.</p></Section>
  <Section title="Remap normal actions"><p>The helper exposes RNS-E/MMI and multi-function wheel short/long presses, the wheel command bytes, and source-change play/pause keys. Extended MMI holds can run configured system commands when <code>features.system_actions</code> is enabled.</p><p>Keep key tokens such as <code>KEY_ENTER</code> exact. Use <code>null</code> to disable a nullable action. The stalk follows the DIS app list rather than a separate editable mapping table.</p></Section>
  <Settings rows={[
    ['input_mappings.mfsw.double_click_ms', 'Double-click window; default 350 ms. MODE taps and DIS selection clicks wait for this window; normal wheel clicks act on release.'],
    ['input_mappings.mfsw', 'Normal steering-wheel key mappings and press handling.'],
    ['input_mappings.mmi', 'RNS-E faceplate key mappings and press handling.'],
    ['display.phone.scroll_wheel_phone_menu', 'Automatic call-control ownership.'],
    ['display.center_display.applist', 'The stalk’s app cycle order.'],
  ]}/>
  <Related links={[['readings', 'Readings wheel examples', 'See page selection, Start, Stop and recording markers.'], ['phone', 'Phone wheel examples', 'See the ownership icon and Accept / Reject / End Call selection.']]}/>
</>; }

function Power() { return <>
  <PageHead location="CONTROLS & BEHAVIOR / VEHICLE STATE" title="Connections, appearance & power">Vehicle state can manage the phone connection, Hudiy appearance, the Pi clock and shutdown. Each behavior has its own config switch.</PageHead>
  <Section title="Bluetooth & Android Auto reconnect"><Table headings={['Vehicle event', 'Configured response']} rows={[
    ['Ignition on', 'Allow connections when connect_on_ignition is enabled.'],
    ['RNS-E radio on without ignition', 'Allow connections when connect_on_radio is enabled.'],
    ['Door opens or unlock/wake event', 'Open a temporary fast-connection window; both durations are configurable.'],
    ['Ignition/radio turns off', 'Disconnect after the configured delay.'],
  ]}/><p>Bluetooth adapter power and Android Auto connect/disconnect requests can be managed separately. This is about connection availability, not changing Android Auto’s appearance mode.</p></Section>
  <Section title="Day/night, source & time"><Table headings={['Feature', 'Behavior']} rows={[
    ['Day/night synchronization', 'Use the vehicle light state for Hudiy’s appearance, which propagates to Android Auto/CarPlay. sync_android_auto additionally sets AA appearance explicitly.'],
    ['TV source controls', 'Send configured pause/resume actions when leaving or returning to the RNS-E TV source.'],
    ['Vehicle time synchronization', 'Set the Pi clock when vehicle time differs beyond the chosen threshold. Match the time-message format and configured IANA timezone.'],
    ['TV simulation', 'Optional tuner-presence frames so the RNS-E can select the TV source used by the video interface.'],
  ]}/></Section>
  <Section title="Power and bus sleep"><Table headings={['Option', 'What triggers it']} rows={[
    ['Ignition/key auto-shutdown', 'Wait for ignition_off or key_pulled to persist for the chosen delay. A return to active state cancels the timer; an active wake signal holds off shutdown.'],
    ['GPIO shutdown', 'Watch the configured BCM pin and polarity; shut down when the derived wake signal remains off for the delay. Match your wiring.'],
    ['Listen-only CAN', 'Wait after bus sleep readiness before making the infotainment CAN interface passive. The fallback is time since ignition-off, even if network-management frames keep arriving.'],
  ]}/></Section>
  <Settings rows={[
    ['features.power_management.connection_management', 'Reconnect triggers, wake windows, managed transports and disconnect delay.'],
    ['features.power_management', 'Power-state, GPIO and bus-sleep behavior.'],
    ['features.day_night_mode', 'Appearance synchronization.'],
    ['features.sync_android_auto', 'Explicit Android Auto appearance synchronization.'],
    ['features.source_controls', 'Source playback actions.'],
    ['features.time_sync', 'Clock drift threshold and vehicle encoding.'],
    ['features.car_time_zone', 'Vehicle clock timezone.'],
  ]}/>
</>; }

function Setup() { return <>
  <PageHead location="SETUP / INSTALLATION" title="Install & update">RNS-E Hudiy runs with Hudiy on a Raspberry Pi connected to the vehicle CAN and the RNS-E video input. Use the project installation instructions for the exact hardware setup.</PageHead>
  <Steps items={[
    ['Check the hardware and existing setup', 'Confirm the video interface, Pi/CAN wiring, cluster type and supported controllers. Back up the existing config and Hudiy settings.'],
    ['Choose the repository and update track', 'The current defaults are DSparks156x/RNS-E-Hudiy and testing. Testing follows that branch; release/beta prefer their latest matching version tag, then the literal branch. A missing reference cancels the update.'],
    ['Run the updater/installer on the Pi', 'Follow the project README. The installer configures dependencies, CAN interfaces and systemd services, and adds missing config fields while preserving existing preferences.'],
    ['Configure the car-specific choices', 'CAN device names, enabled displays, default app/order, button mappings, connection behavior and power wiring. Export your edits from the config helper.'],
    ['Restart affected services and check the result', 'Verify Hudiy data arrives, the DIS shows the chosen app, and DataView opens. Capture service logs if an input or display does not behave as expected.'],
  ]}/>
  <Section title="Which settings belong where?"><Table headings={['You want to change…', 'Edit here']} rows={[
    ['DIS app order, navigation, phone takeover, button mappings or power behavior', 'Configuration helper → config.json'],
    ['Eight-slot DIS pages, units/icons/precision, linked recording profiles', 'DataView → Data & Logs → DIS pages'],
    ['Values included in a named recording', 'DataView → Data & Logs → Record → Choose values'],
    ['Which ECU measuring groups are visible', 'DataView → Diagnostics → selected module'],
    ['Firmware files available to controller tools', 'Pi file portal upload targets / configured firmware directories'],
  ]}/></Section>
  <Section title="Optional and older views"><p>The car widget has a model/color artwork picker. The older boost widget has a selectable gauge and four bars with local channel/theme choices and legacy units. They coexist with DataView and use older group subscriptions.</p><p>Openpilot has experimental renderer/mock support, but its transport is hard-disabled because its legacy CAN identifiers conflict with Haldex. Enabling the config key does not activate it.</p></Section>
  <SourceLink source="README.md">Project installation instructions</SourceLink><SourceLink source="install.sh">Installer source</SourceLink>
  <Related links={[[ 'configuration', 'Edit the config', 'Latest selected-branch config, descriptions and export.' ],['files','Collect support logs','Save recent service journals and API captures.']]}/>
</>; }

function Configuration({ selection, setSelection }) { return <>
  <PageHead location="SETUP / CONFIG.JSON" title="Configuration helper">Load a branch’s config, find a setting, read its description, and export your changes. Page/profile editing lives in DataView; this helper edits the project config.</PageHead>
  <ConfigLaunch selection={selection} setSelection={setSelection}/>
  <Section title="One complete settings reference"><p>The config helper is the reference: it shows every setting in the config you load, with descriptions for known settings and editable fields for branch-specific additions. Search covers names, paths, descriptions and values.</p><p>The feature pages link to the settings relevant to their workflows. Those links open the helper with that path already searched and the source chosen above. They are shortcuts into the full config, rather than another copy of its reference.</p></Section>
  <Section title="Use the helper"><Steps items={[
    ['Open or import', 'Open fetches the selected public repository/branch config.json. Import JSON reads a saved file. The initial repo/branch defaults are your testing branch.'],
    ['Search and edit', 'Search setting names, descriptions, paths or values. All loaded groups remain available, including long-press mappings and structured JSON settings.'],
    ['Check invalid fields', 'Invalid numeric or JSON edits show an error and block export until corrected. Unknown branch-specific settings remain editable and keep their JSON types.'],
    ['Download and apply', 'Download config.json, put it in the project config location on the Pi, then restart affected services. Downloading does not install it remotely.'],
  ]}/><p><strong>Undo load</strong> restores the config that was open before the last load/import. Edits stay in this tab; nothing is written back to GitHub.</p></Section>
  <Section title="Common starting points"><Table headings={['Goal', 'Settings group']} rows={[
    ['Choose startup app and stalk order', 'Cluster display → Center display → mode / applist'],
    ['Change navigation switching', 'Cluster display → Navigation'],
    ['Control call-page and wheel takeover separately', 'Cluster display → Phone'],
    ['Change normal hardware actions', 'Buttons & wheel'],
    ['Reconnect phone or adjust shutdown', 'Power & integration'],
    ['Set upload PIN or firmware directories', 'File portal / controller storage groups'],
  ]}/></Section>
  <p>Imports preserve unknown fields, arrays, objects, null values and legacy flags. They are not silently migrated to this checkout’s schema. Descriptions identify known older settings when the current runtime uses a replacement.</p>
</>; }

function Files() { return <>
  <PageHead location="VEHICLE DATA / FILE PORTAL" title="Files, uploads & logs">Upload controller binaries and get recordings, debug logs and readouts off the Pi from a phone or computer. Collections keep firmware libraries, drive data and troubleshooting files easy to find.</PageHead>
  <Figure src="file-portal-overview.jpg" caption="Sample files in the actual portal with a Hudiy palette. Drive recordings, debug logs and controller files have separate views, with search, sorting and direct downloads."/>
  <div className="address-panel"><span>OPEN ON YOUR PHONE OR COMPUTER</span><code>http://&lt;Pi-IP&gt;:5003/files</code><p>Replace &lt;Pi-IP&gt; with the Pi’s address. The guide itself does not connect to the car.</p></div>
  <Section title="Upload a controller binary"><Figure src="file-portal-upload.jpg" caption="Controller files: choose the upload target, select a supported file, then validate and save it to the matching firmware library."/><Steps items={[
    ['Open Upload file and choose the target', 'Use Save to collection to choose Haldex, PQ EPS or Exhaust valve. The target sets the accepted formats and size limit.'],
    ['Choose a file and validate it', 'Select the binary or bundle and enter the upload PIN if one is configured. Validation checks its extension, size and target-specific image structure before saving. Existing filenames are not overwritten.'],
    ['Select it in the controller tool', 'Refresh the appropriate DataView controller panel to see the accepted file. Uploading puts it in the library; the separate controller workflow performs the flash.'],
  ]}/><Table headings={['Target', 'Supported input']} rows={[
    ['Haldex Gen4', '320 KiB CPU-linear .bin firmware image.'],
    ['PQ EPS', '384 KiB full firmware image or exact 4 KiB steering dataset .bin.'],
    ['Exhaust valve controller', 'ZIP containing can-update.json and both native slot binaries, or the manifest and two slot files uploaded separately.'],
  ]}/><p>The PIN protects uploads. Download access stays available on the Pi’s network.</p></Section>
  <Section title="Download drive recordings"><p>These CSVs are useful for looking through a run afterward, comparing Haldex engagement with vehicle inputs, or investigating the CAN traffic itself.</p><Steps items={[
    ['Record in DataView → AWD → Drive Logger', 'Choose Haldex fused or Raw CAN and press Start Logging. Understeer, Oversteer and Launch add markers; Stop Recording finishes the file.'],
    ['Open Drive recordings in the portal', 'Find the timestamped haldex_*.csv or raw_can_*.csv. Download a single file or the collection ZIP.'],
  ]}/><Table headings={['Profile', 'What the CSV contains']} rows={[
    ['Haldex fused', 'Haldex telemetry alongside vehicle speed, RPM, steering, braking and other CAN/selected measuring-group readings.'],
    ['Raw CAN', 'One row per frame, with bus/source, CAN ID, DLC and payload bytes. Diagnostic events can be included when configured.'],
  ]}/><p><strong>Named Data & Logs recordings</strong> use a different store. Their full CSV is generated from <strong>Data & Logs → Review → CSV</strong>; it is not automatically a file in this portal.</p><a className="text-button" href="#recordings">Named recordings & graph review →</a></Section>
  <Section title="Get debug logs after a problem"><Figure src="file-portal-debug.jpg" caption="Debug logs: saved service journals, current service output, Hudiy API events and flash-operation reports. Download a collection or gather all log collections into one ZIP."/><Steps items={[
    ['Use Save Logs close to the event', 'The Hudiy action saves recent service journals and current/previous API captures into a dated, numbered folder. Each press keeps a separate snapshot.'],
    ['Open Debug logs', 'Choose the relevant collection or download All logs ZIP. ZIPs retain the nested paths so dated captures stay together.'],
    ['Keep the event context', 'Include what you pressed, the visible app and the active call/track/maneuver. That usually helps more than “it did a thing.”'],
  ]}/><Table headings={['Collection', 'What to look for']} rows={[
    ['Service & error logs', 'Saved journals, including the dated/numbered Save Logs snapshots. Services and history duration are configurable.'],
    ['Live service logs', 'Current service output and errors. On the installed Pi these are RAM-backed, so collect them before a reboot.'],
    ['Hudiy API captures', 'Always-on, provider-tagged projection/media/navigation/phone events. Current and previous rotated captures are available.'],
    ['Flashing operation logs', 'Identification, transfer and recovery reports from recent controller operations.'],
  ]}/></Section>
  <Section title="Controller readouts & ZIP downloads"><p><strong>Controller files</strong> also includes Haldex and EPS readouts: firmware/EEPROM binaries and their capture reports. Keep each image with its report so you know what was read.</p><p>A collection ZIP includes its permitted files and preserves subfolders. <strong>All logs ZIP</strong> combines the log collections; firmware and readouts stay in their own collections. The default archive limit is 256 MiB before compression.</p></Section>
  <Related links={[[ 'controllers', 'Controller workflows', 'Validate, query, transfer or read out the selected controller.' ],['recordings','Named recordings','Profiles, graphs, markers and CSV.']]}/>
</>; }

function Tools() { return <>
  <PageHead location="SETUP / DEVELOPMENT" title="Developer tools">Helpers for making cluster artwork and text, inspecting Hudiy colors, testing layouts and investigating CAN data. Everyday configuration and file access have their own pages.</PageHead>
  <Section title="Browser helpers"><div className="tool-grid">{[
    ['bitmap_tool.html', 'Bitmap tool', 'Convert a bitmap into icon data for the project. Use it when adding or adjusting pixel artwork.'],
    ['audscii_helper.html', 'AUDSCII helper', 'Inspect cluster character encoding and generate supported text bytes.'],
    ['theme_viewer.html', 'Theme viewer', 'Paste/inspect Hudiy’s light and dark palette to see the named color roles.'],
  ].map(([file, title, text]) => <a key={file} className="tool-card" href={`./tools/${file}`} target="_blank" rel="noreferrer"><h3>{title} ↗</h3><p>{text}</p></a>)}</div></Section>
  <Section title="Image & GIF tester"><p>The React image tester uses the actual image-processing pipeline. Load an image/GIF, compare processing settings, play or scrub frames, and export config snippets.</p><SourceLink source="tools/dis_image_tester/README.md">Run the image tester</SourceLink></Section>
  <Section title="Emulator & physical bench"><p>The browser DIS emulator paints drawing commands with captured cluster fonts. It is useful for checking text, graphics and app transitions without sitting in the car.</p><p>The physical bench console works with a real cluster. Simulated pixels and physical protocol testing answer different questions; the sample images here are renderer output.</p><SourceLink source="dis_emulator/bench_cluster/README.md">Bench console</SourceLink></Section>
  <Section title="CAN & vehicle-value tools"><Table headings={['Tool', 'Purpose']} rows={[
    ['Measuring-group inspector', 'Inspect controller group responses and compare fields.'],
    ['CAN dump/correlation tools', 'Capture traffic and correlate byte/bit changes with diagnostic values.'],
    ['Vehicle-value catalog', 'Read the meaning, units, provider and quality of named values.'],
    ['DHU driving helper', 'Drive the Android Auto desktop test environment with keyboard inputs to exercise navigation.'],
  ]}/><SourceLink source="tools/README.md">Tool commands</SourceLink><SourceLink source="vehicle_data/CATALOG.md">Value catalog</SourceLink></Section>
  <Related links={[[ 'configuration', 'Configuration helper', 'Edit the installed project’s settings.' ],['files','Files & support logs','Pi downloads, uploads and captures.']]}/>
</>; }

export const Pages = { overview: Overview, readings: Readings, navigation: Navigation, media: Media, phone: Phone, acceleration: Acceleration, 'top-display': TopDisplay, dataview: Dashboards, recordings: Recordings, diagnostics: Diagnostics, controllers: Controllers, controls: Controls, power: Power, setup: Setup, configuration: Configuration, files: Files, tools: Tools, ...HowToPages };
