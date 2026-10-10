import React, { useState } from 'react';
import { DemoImage, Figure, FeatureDemo, Note, PageHead, Related, Section, Settings, SourceLink, Steps, Table, ConfigLaunch } from './ui';
import { WheelExplainer } from './WheelExplainer';
import RnseFaceplate from './RnseFaceplate';
import { NavigationShowcase } from './NavigationShowcase';
import { howToGroup, howToTopics, HowToPages } from './HowToGuides';
import { getStartedGroups, getStartedTopics, GetStartedPages } from './GetStarted';

export const groups = [
  { id: 'start', title: 'OVERVIEW' },
  { id: 'dis', title: 'CLUSTER DISPLAY' },
  { id: 'data', title: 'VEHICLE DATA' },
  { id: 'controls', title: 'CONTROLS & BEHAVIOR' },
  ...getStartedGroups,
  { id: 'setup', title: 'SETTINGS & TOOLS' },
  howToGroup,
];
export const topics = [
  { id: 'overview', group: 'start', title: 'What this adds', icon: '⌂', summary: 'Screens and features in this fork', keywords: 'overview capabilities features' },
  { id: 'readings', group: 'dis', title: 'Custom readings', icon: '▦', summary: 'Build eight-slot DIS pages and link recordings', keywords: 'car_info values units precision icons page editor slots white red logging' },
  { id: 'navigation', group: 'dis', title: 'Navigation', icon: '↱', summary: 'Turn guidance and automatic switching', keywords: 'directions maneuver distance approach bar stock bitmap icons' },
  { id: 'media', group: 'dis', title: 'Music & album art', icon: '♫', summary: 'Now playing and cover art', keywords: 'music media coverart playback scrolling artist album' },
  { id: 'phone', group: 'dis', title: 'Phone calls', icon: '☎', summary: 'Caller details, wheel selection and call takeover', keywords: 'phone call accept reject caller end wheel mode takeover' },
  { id: 'acceleration', group: 'dis', title: 'Acceleration timing', icon: '◴', summary: 'Speed-range and distance-run timers', keywords: '0-60 timer quarter mile tolerance speed reset' },
  { id: 'top-display', group: 'dis', title: 'Top display', icon: '☰', summary: 'Independent two-line content, priority and formatting', keywords: 'top lines strip phone navigation media metadata scrolling priority format' },
  { id: 'dataview', group: 'data', title: 'Vehicle dashboards', icon: '◴', summary: 'Read the Engine, Transmission and AWD screens', keywords: 'boost fuel pressure knock timing clutch selector Haldex Stock Perf Comp torque smoothing' },
  { id: 'recordings', group: 'data', title: 'Record & review', icon: '≋', summary: 'Profiles, graphs, events, markers and CSV', keywords: 'data logs recording traces cursor value picker export' },
  { id: 'diagnostics', group: 'data', title: 'Faults & measuring groups', icon: '⊞', summary: 'Read/clear DTCs and inspect ECU measuring groups', keywords: 'scanner VCDS fault codes module picker TP2 freeze frame' },
  { id: 'controllers', group: 'data', title: 'Module flashing', icon: '⚙', summary: 'Flash and read out modules: Haldex Gen4, PQ EPS, my exhaust valve', keywords: 'module controller tools flashing flash update steering dataset EEPROM Gen4 valve open close recovery firmware unconfirmed' },
  { id: 'controls', group: 'controls', title: 'Buttons & wheel', icon: '⊕', summary: 'Normal mappings, DIS focus and phone takeover', keywords: 'MODE double click stalk rocker MMI steering long press volume hudiy menu bar shortcuts' },
  { id: 'power', group: 'controls', title: 'Connections & power', icon: '⏻', summary: 'Reconnect, day/night, time sync and shutdown', keywords: 'ignition Bluetooth Android Auto CarPlay radio GPIO listen only source unlock wake' },
  { id: 'manager', group: 'setup', title: 'RNS-E Manager', icon: '◧', summary: 'Settings, services, logs and picture controls on the head unit', keywords: 'manager settings services restart logs journal brightness LCD gamma contrast colour ADC tuning source label 5004' },
  { id: 'configuration', group: 'setup', title: 'Configuration helper', icon: '⚙', summary: 'Load, edit and export the selected branch config', keywords: 'repo branch config.json settings import download' },
  { id: 'files', group: 'data', title: 'File portal', icon: '▤', summary: 'Firmware and config uploads, recordings and debug-log downloads', keywords: 'binary bin file upload PIN ZIP archive folders CSV download Save Logs API readout configuration replace' },
  { id: 'tools', group: 'setup', title: 'Developer tools', icon: '↗', summary: 'Artwork, text, themes, emulation and CAN tools', keywords: 'AUDSCII bitmap GIF image tester DHU bench catalog measuring inspector' },
  ...getStartedTopics,
  ...howToTopics,
];

function Overview() {
  const [demo, setDemo] = useState('readings');
  const demos = {
    readings: { title: 'Custom readings', src: 'dis-readings-controls.gif', description: 'Eight values per page, multiple pages, and record controls on the wheel.', link: 'readings' },
    navigation: { title: 'Navigation', src: 'dis-navigation-approach.gif', description: 'Turn arrow, distance, street name and an approach bar.', link: 'navigation' },
    media: { title: 'Now playing', src: 'dis-media-scroll.gif', description: 'Track info, progress and scrolling text.', link: 'media' },
    phone: { title: 'Calls', src: 'dis-phone.png', description: 'Caller name, plus Accept, Reject and End Call from the wheel.', link: 'phone' },
  };
  const shown = demos[demo];
  return <>
    <div className="hero overview-hero"><div><div className="eyebrow">DSPARKS156X / RNS-E-HUDIY</div><h1>RNS-E Hudiy<br/>features & setup</h1><p className="lead">My fork of the RNS-E + Raspberry Pi + Hudiy setup. It takes over the cluster display, maps the RNS-E and wheel buttons, shows live engine, transmission and AWD data, reads faults, records data and flashes a few controllers.</p><div className="hero-actions"><a className="primary-button" href="#hardware">Get set up →</a><a className="text-button" href="#readings">Build a DIS page ↗</a></div></div><div className="cluster-showcase"><div className="showcase-top"><span>ON THE DIS</span><span>128 × 96</span></div><DemoImage key={shown.src} pixel src={shown.src} alt={shown.description}/><div className="demo-tabs" aria-label="DIS examples">{Object.entries(demos).map(([id, value]) => <button key={id} onClick={() => setDemo(id)} aria-pressed={id === demo}>{value.title}</button>)}</div><p className="showcase-description">{shown.description}</p><a className="source-link" href={`#${shown.link}`}>How this works →</a></div></div>
    <Section title="The main features">
      <div className="feature-pair">
        <a className="feature-card sage" href="#readings"><div className="card-heading"><span>CLUSTER DISPLAY</span><span className="arrow">↗</span></div><h3>Custom DIS pages</h3><p>Pick eight values per page, with units, decimals and icons. Start, stop and mark a recording from the wheel.</p><span className="card-cta">Build and use a page →</span></a>
        <a className="feature-card sand" href="#recordings"><div className="card-heading"><span>DATA & LOGS</span><span className="arrow">↗</span></div><h3>Recording & review</h3><p>Pick values, record, drop markers, look at the graphs on the head unit, export CSV.</p><span className="card-cta">Profiles, graphs and export →</span></a>
      </div>
      <FeatureDemo src="dataview-engine.gif" pixel={false} caption="Engine dashboard: airflow and boost, ignition timing and cylinder retard, fuel system and temperatures." title="Engine, Transmission and AWD dashboards"><p>Actual vs. requested boost and rail pressure, per-cylinder timing pull, clutch pressures, selector travel, and Haldex telemetry with mode buttons.</p><a className="text-button inline-link" href="#dataview">Read the dashboards →</a></FeatureDemo>
    </Section>
    <div className="feature-index">
      {[
        ['navigation', 'Navigation', 'Turn arrow, distance and approach bar. Pops up near a turn.'],
        ['media', 'Music & album art', 'Track info and album covers.'],
        ['phone', 'Phone calls', 'Caller info; answer, reject or hang up with the wheel.'],
        ['diagnostics', 'Fault codes & measuring groups', 'Read and clear faults, view measuring groups.'],
        ['files', 'File portal', 'Upload firmware or configs from your phone. Download logs and recordings.'],
        ['controllers', 'Module flashing', 'Flash and read out the Haldex Gen4, steering datasets on the PQ EPS, and my exhaust valve.'],
        ['controls', 'Wheel, buttons & vehicle behavior', 'Stock buttons drive Hudiy. Reconnect, day/night, clock and shutdown follow the car.'],
      ].map(([id, title, text]) => <a href={`#${id}`} key={id}><h3>{title}<span>↗</span></h3><p>{text}</p></a>)}
    </div>
    <Related links={[
      ['configuration', 'Configuration helper', 'Edit config.json in the browser.'],
      ['files', 'Get files off the Pi', 'Logs, readouts and uploads.'],
      ['tools', 'Developer tools', 'Bitmap, text and theme helpers; image tester and emulator.'],
    ]}/>
  </>;
}

function Readings() { return <>
  <PageHead location="CLUSTER DISPLAY / READINGS" title="Custom DIS readings">Eight values per page on the white DIS, as many pages as you want, and a record button you can work from the wheel. Red clusters get the old five-line Car Info screen instead.</PageHead>
  <Section title="On the cluster"><p>Double-click MODE to give the wheel to the page. Scroll to the page name, play/stop or the marker flag, then click. Pick the page name and scroll to switch pages.</p><WheelExplainer mode="readings"/></Section>
  <Section title="Build a page">
    <Figure src="dataview-dis-editor.jpg" caption="DataView → Data & Logs → DIS pages."/>
    <Steps items={[
      ['Open DataView → Data & Logs → DIS pages', 'Pick a page or tap + for a new one. Slots are 1L/1R to 4L/4R, same as the cluster.'],
      ['Tap a slot, pick a value', 'Browse by system or search.'],
      ['Set units, decimals (0–3), font and icon', 'Then Done.'],
      ['Apply', 'Done only edits the draft. Apply saves it.'],
    ]}/>
    <p><strong>Page settings</strong> renames, duplicates and reorders pages. <strong>Log:</strong> picks which recording profile the play button starts.</p>
  </Section>
  <Section title="Worth knowing"><ul>
    <li>The DIS and the touchscreen control the same recording. DataView’s service runs the recorder, so it has to be running even if you only use the wheel.</li>
    <li>Each slot has its own units. The unit settings in config.json don’t touch these pages.</li>
    <li>Missing or stale values show as unavailable, not as an old number.</li>
  </ul></Section>
  <Section title="Red-cluster Car Info"><FeatureDemo src="dis-car-info-legacy.png" caption="The red/low-res Car Info screen: boost, airflow, ignition timing, oil and coolant." title="Five fixed readings"><p>With <code>display.center_display.high_resolution</code> off, you get this instead of the page editor and record header. Set it to match your cluster.</p></FeatureDemo></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Include car_info. Its position sets where it sits in the stalk cycle.'],
    ['display.center_display.high_resolution', 'On for white (eight slots), off for red (five lines).'],
    ['data_logs.directory', 'Where pages, profiles and recordings live. Default ~/logs/data-logs.'],
  ]}/>
  <Related links={[[ 'recordings', 'Recording profiles & review', 'Choose what to record, inspect graphs and export CSV.' ],['controls','Wheel ownership','Manual control, phone takeover and double-click timing.']]}/>
</>; }

function Navigation() { return <>
  <PageHead location="CLUSTER DISPLAY / NAVIGATION" title="Navigation on the DIS">Turn arrow, distance, street name and an approach bar, from Hudiy’s navigation data. It can pop up near a turn and get out of the way after.</PageHead>
  <Section title="Stock icons & bitmap artwork"><NavigationShowcase/><p>Long street names scroll. You only get what Hudiy’s nav source sends.</p><p>On the white DIS, <code>display.center_display.navigation.icon_style</code> picks <code>stock</code> or <code>bitmap</code> (default bitmap). The red DIS uses its old layout.</p></Section>
  <Section title="Automatic switching"><ul>
    <li><strong>New or changed maneuver:</strong> nav shows for 5 seconds, then goes back to what you had.</li>
    <li><strong>Within 500 m:</strong> nav stays up.</li>
    <li><strong>Back out past 1000 m</strong> (return threshold): it resets and can pop up again.</li>
    <li><strong>Switch away yourself:</strong> it leaves you alone until the next maneuver.</li>
  </ul><p>That's all within our center display. <code>claim_on_nav</code> goes further: when a route starts it switches the cluster to our nav page from whatever cluster page you were on, and gives it back when the route ends.</p></Section>
  <Settings rows={[
    ['display.center_display.navigation.auto_switch', 'Pop-ups on/off.'],
    ['display.center_display.navigation.auto_switch_approach_threshold', 'Meters where nav stays up.'],
    ['display.center_display.navigation.auto_switch_return_threshold', 'Meters where it resets. Keep it above the approach threshold.'],
    ['display.center_display.navigation.approach_bar_max_distance', 'Range of the approach bar (300 m by default). Doesn’t affect switching.'],
    ['display.center_display.navigation.claim_on_nav', 'Switch the cluster to our nav page when a route starts.'],
    ['display.units.speed', 'Imperial, metric or follow the car.'],
  ]}/>
  <Related links={[[ 'top-display', 'Top display', 'Keep turn info above another page.' ],['controls','Change apps','Stalk and steering wheel.']]}/>
</>; }

function Media() { return <>
  <PageHead location="CLUSTER DISPLAY / MUSIC" title="Music & album art">Track info and progress on the DIS, and the album cover when the song changes.</PageHead>
  <FeatureDemo src="dis-media-scroll.gif" caption="Title, artist and album scroll to fit; position and duration stay put." title="Now playing"><p>Title, artist, album, position and duration from Hudiy. Long lines scroll.</p></FeatureDemo>
  <FeatureDemo src="dis-cover-art.png" caption="Cover art on the white DIS, balanced preset." title="Album cover art"><p>With <code>brief</code> on, a new track shows its cover for 5 seconds while you’re on Media. Add <code>coverart</code> to the app list to have it as its own page.</p><p>Presets: <strong>legacy</strong> (your saved args), <strong>balanced</strong> (ordered dither), <strong>photo</strong> (error diffusion), <strong>text</strong> (hard threshold).</p></FeatureDemo>
  <Section title="More covers"><p>Pick the preset that suits what you listen to. These are made-up covers run through the real pipeline.</p><div className="cover-grid">
    <Figure pixel src="dis-cover-sunset.png" caption="Photo preset: gradients and tones."/>
    <Figure pixel src="dis-cover-type.png" caption="Text preset: crisp type and logos."/>
    <Figure pixel src="dis-cover-record.png" caption="Balanced preset: steady texture."/>
  </div></Section>
  <FeatureDemo src="dis-animation.gif" caption="Animated GIF at 64 × 48, about 10 fps, through the production bitmap path." title="Pushing pixels"><p>The DIS was never meant to show pictures. Every cover above is a full 128 × 96 bitmap pushed over CAN to the cluster, and it's fast enough to actually use.</p><p>It'll even do animation, at lower resolution and around 10 fps. Not really a feature, more proof that it can be done.</p></FeatureDemo>
  <Settings rows={[
    ['display.center_display.applist', 'Add media and/or coverart.'],
    ['display.center_display.coverart', 'Brief display, preset and processing args.'],
    ['display.text_scrolling', 'Scroll speed, end pauses, loop gap, line offset.'],
    ['display.top_display', 'Media lines on the top display.'],
  ]}/>
  <Related links={[[ 'controls', 'Media controls', 'Wheel and faceplate playback.' ],['top-display','Top display','Track info above another page.']]}/>
</>; }

function Phone() { return <>
  <PageHead location="CLUSTER DISPLAY / PHONE" title="Phone calls">Caller info on the DIS. Use the wheel to Accept or Reject, then End Call.</PageHead>
  <Section title="Wheel selection"><p>The little wheel icon means the call has the wheel. Scroll to pick, click to do it. Works whether the call is on the center page or only on the top display.</p><WheelExplainer mode="phone"/></Section>
  <Section title="Two separate settings"><ul>
    <li><code>claim_on_phone</code>: switch the cluster to our phone page when a call starts (from the trip computer or wherever), and give it back after.</li>
    <li><code>scroll_wheel_phone_menu</code>: give the call the wheel automatically. If you’ve already got the wheel on a readings page, that wins. Double-click MODE to keep normal wheel actions for this call.</li>
  </ul></Section>
  <Settings rows={[
    ['display.center_display.applist', 'Add phone for a center call page.'],
    ['display.phone.claim_on_phone', 'Switch the cluster to our phone page when a call starts.'],
    ['display.phone.scroll_wheel_phone_menu', 'Give the call the wheel automatically.'],
    ['display.top_display', 'Phone priority and line formats on the top display.'],
  ]}/>
  <Related links={[[ 'controls', 'Wheel controls', 'Taking the wheel and giving it back.' ],['top-display','Top display','Call info above another page.']]}/>
</>; }

function Acceleration() { return <>
  <PageHead location="CLUSTER DISPLAY / ACCELERATION" title="Acceleration timing">0–60s, roll-ons and quarter miles, timed off CAN speed. Four rows, you pick what each one times.</PageHead>
  <FeatureDemo src="dis-acceleration-run.gif" caption="0–60, 0–30, 40–70 mph and live speed, simulated run." title="Four rows, your choice"><p>Start and finish times are interpolated between CAN samples. The ± is the sample-timing tolerance. It’s CAN speed, not GPS, so treat it accordingly.</p></FeatureDemo>
  <Section title="Row formats"><ul>
    <li><code>0-60</code>, <code>40-70</code>: speed range, in your speed units.</li>
    <li><code>1/4</code>: quarter mile (or quarter km in metric). Decimal distances under 10 work too.</li>
    <li><code>1000</code>: bigger numbers are feet (imperial) or meters (metric).</li>
    <li><code>speed</code>: just live speed.</li>
  </ul><p>Timers reset when you come to a stop (configurable), or when you cycle away and back.</p></Section>
  <Settings rows={[
    ['display.center_display.acceleration_test', 'The four rows, reset-on-stop and the ± display.'],
    ['display.units.speed', 'Imperial, metric, or follow the car.'],
  ]}/>
  <Related links={[[ 'controls', 'Stalk & wheel controls', 'Getting to the acceleration page.' ]]}/>
</>; }

function TopDisplay() { return <>
  <PageHead location="CLUSTER DISPLAY / TOP DISPLAY" title="Top display">The two lines above the center area. They show phone, nav or media no matter which center page you’re on.</PageHead>
  <FeatureDemo src="dis-top-media.gif" caption="Top lines on their own, scrolling track and artist." title="Content above the center page"><p>Keep the track up top while the center shows readings, for example. Long text scrolls using the shared scroll settings.</p></FeatureDemo>
  <Section title="Priority and line content"><p><code>display.top_display.applist</code> sets priority. First app with something to show wins. Default: phone, nav, media.</p><ul>
    <li><strong>Media:</strong> title, artist, album, source. A separate first line is used when the center is already on Media.</li>
    <li><strong>Navigation:</strong> description, maneuver, distance.</li>
    <li><strong>Phone:</strong> caller, state, name, connection, battery, signal.</li>
  </ul><p>Join fields with a hyphen, like <code>title-artist</code>.</p></Section>
  <Settings rows={[
    ['display.top_display.applist', 'Priority order.'],
    ['display.top_display', 'Fields on each line.'],
    ['display.text_scrolling', 'Scroll speed, pauses, loop gap, line offset.'],
  ]}/>
  <Related links={[[ 'media', 'Music & album art', 'Center media page and cover art.' ],['phone','Phone calls','Call info and wheel actions.'],['navigation','Navigation','Center turn guidance.']]}/>
</>; }

function Dashboards() {
  const [tab, setTab] = useState('engine');
  const screens = {
    engine: { title: 'Engine', src: 'dataview-engine.gif', caption: 'Air/boost left, RPM and timing center, fuel right, temperatures below.' },
    transmission: { title: 'Transmission', src: 'dataview-transmission.jpg', caption: 'Clutch pressures and related values left; selector travel right.' },
    awd: { title: 'AWD', src: 'dataview-awd.jpg', caption: 'Haldex readings, requested vs. active mode, and the Drive Logger.' },
  };
  const shown = screens[tab];
  return <>
    <PageHead location="VEHICLE DATA / DATAVIEW" title="Vehicle dashboards">DataView has Engine, Transmission and AWD dashboards, next to Data & Logs and Diagnostics. Tap the tabs or swipe.</PageHead>
    <div className="screen-tabs" aria-label="Dashboard guides">{Object.entries(screens).map(([id, screen]) => <button key={id} aria-pressed={id === tab} onClick={() => setTab(id)}>{screen.title}</button>)}</div>
    <Figure key={shown.src} src={shown.src} caption={shown.caption}/>
    {tab === 'engine' && <Section title="Engine"><ul>
      <li><strong>Air & boost:</strong> MAF in g/s, actual boost in mbar with a marker for requested.</li>
      <li><strong>RPM & ignition:</strong> timing advance, plus four bars for per-cylinder timing pull.</li>
      <li><strong>Fuel:</strong> actual and requested rail pressure, pump duty, injection time.</li>
      <li><strong>Temps:</strong> oil, ambient, intake and coolant.</li>
    </ul><p>Boost is <strong>absolute</strong>, so it includes atmosphere. ~1000 mbar is zero boost.</p></Section>}
    {tab === 'transmission' && <Section title="Transmission"><ul>
      <li><strong>Clutches:</strong> actual pressure, shaft speed, requested torque and valve current for each clutch.</li>
      <li><strong>Selector travel:</strong> 1/3, 2/4, 5/N and 6/R.</li>
      <li><strong>Status row:</strong> fluid, module and clutch-oil temps.</li>
    </ul></Section>}
    {tab === 'awd' && <Section title="AWD"><ul>
      <li><strong>Pressure & torque:</strong> Haldex oil pressure and an estimated torque.</li>
      <li><strong>Valve & control:</strong> N273 opening/current, commanded torque, slip-control torque.</li>
      <li><strong>Stock / Perf / Comp:</strong> requests that mode. Check Active mode to see if the controller took it. The Haldex button on the Hudiy bar cycles the same modes.</li>
      <li><strong>ARMED:</strong> safety-token state. Also oil/plate temp, supply voltage and operating modes.</li>
      <li><strong>Drive Logger:</strong> the older Haldex/raw CAN logger. See <a href="#files">File portal</a>.</li>
    </ul><p><code>haldex.default_mode</code> forces a mode at startup; <code>null</code> restores the last one.</p><Note>Mode control and telemetry need compatible custom Haldex firmware on the controller. What Stock/Perf/Comp actually do is up to that firmware.</Note></Section>}
    <Section title="Smoothing and missing values"><p>The <strong>~</strong> button toggles smoothing. It only smooths the gauges; the ECU isn’t sending any faster. Missing or stale values show as unavailable.</p></Section>
    <Related links={[[ 'recordings', 'Record these values', 'Profiles, markers and review.' ],['controllers','Module flashing','Haldex firmware and readouts.']]}/>
  </>;
}

function Recordings() { return <>
  <PageHead location="VEHICLE DATA / DATA & LOGS" title="Record, review & export">Pick values, record, drop markers, look at the graphs on the head unit, export CSV.</PageHead>
  <Figure src="dataview-record.jpg" caption="Record: pick a profile, choose values, start, mark."/>
  <Section title="Record"><Steps items={[
    ['Data & Logs → Record, pick a profile', '+ makes a new profile from the current one’s values. Profile settings renames it and allows estimated/unverified values.'],
    ['Choose values', 'Browse by system or search. Selected shows only what you picked.'],
    ['Start, then Mark when something happens', 'Recording keeps going if you switch tabs.'],
    ['Stop & save, or Stop & review', 'Review jumps straight to the end of the recording.'],
  ]}/></Section>
  <Figure src="dataview-value-picker.jpg" caption="The value picker, grouped by system and function."/>
  <Section title="Review"><Figure src="dataview-review.jpg" caption="Review: traces grouped by unit, cursor, markers, time window."/><ul>
    <li><strong>Traces:</strong> pick what to graph. Graphs are grouped by unit.</li>
    <li><strong>Tap a graph:</strong> cursor with values at that moment. + / − zoom around it.</li>
    <li><strong>Earlier / Later / Last 10s / Last 30s / Full log:</strong> move the window.</li>
    <li><strong>Events:</strong> text values and status changes, searchable.</li>
    <li><strong>CSV:</strong> the whole recording, even past the on-screen sample limit.</li>
  </ul><p>Bad or stale samples show as gaps, not as a flat line. A recording keeps the profile it started with, so editing the profile later doesn’t change it. Restarting DataView ends a running recording.</p><a className="text-button inline-link" href="#record-a-run">What to record and how to read it →</a></Section>
  <Section title="Start it from the DIS"><p>Set the page’s <strong>Log:</strong> profile in the DIS editor. The cluster’s play/stop/flag run the same recording.</p><a className="text-button inline-link" href="#build-readings">Build a readings page →</a></Section>
  <Section title="Two recorders"><ul>
    <li><strong>Data & Logs</strong> (this page): named values, graphs, CSV export. Lives in <code>data_logs.directory</code>.</li>
    <li><strong>AWD → Drive Logger</strong>: the older Haldex/raw CAN logger with Understeer/Oversteer/Launch markers. Writes CSVs straight to the file portal.</li>
  </ul></Section>
  <Related links={[[ 'readings', 'Custom DIS readings', 'Pages and their linked profile.' ],['files','File portal','Drive Logger CSVs and debug logs.']]}/>
</>; }

function Diagnostics() { return <>
  <PageHead location="VEHICLE DATA / DIAGNOSTICS" title="Fault codes & measuring groups">TP2.0 diagnostics on the touchscreen: pick a module, read or clear faults, watch up to three measuring groups.</PageHead>
  <Figure src="dataview-diagnostics.jpg" caption="Diagnostics module picker. The exhaust controller has its own tile."/>
  <Section title="Fault codes"><Steps items={[
    ['Pick a module', 'Engine, Auto Trans, AWD, and so on.'],
    ['Read DTCs', 'Codes come back with their status, plus freeze-frame data where the module supports it. “No fault codes found” also shows before you’ve read anything, so actually press Read.'],
    ['Clear DTCs', 'Then read again to check.'],
  ]}/><p>Engine works well. Other modules, your mileage may vary.</p></Section>
  <Section title="Measuring groups"><Figure src="dataview-diagnostics-engine.jpg" caption="Engine groups 3, 20 and 115. Values are synthetic."/><p>Tap Grp 1, 2 or 3 and type a group number. Clear it to free that slot. Selections are remembered per module until DataView restarts.</p><p>Engine examples: <strong>3</strong> RPM, MAF and timing; <strong>20</strong> per-cylinder timing pull; <strong>115</strong> requested vs. actual boost. Other ECUs number their groups differently.</p></Section>
  <Section title="Using VCDS or another scanner"><p>Hudiy app menu → <strong>Toggle Diagnostics</strong> first, so this project stops talking to the modules. Passive CAN values keep working.</p></Section>
  <Related links={[[ 'controllers', 'Module flashing', 'Haldex Gen4, PQ EPS and exhaust.' ],['dataview','Dashboards','Live Engine, Transmission and AWD.']]}/>
</>; }

function Controllers() { return <>
  <PageHead location="VEHICLE DATA / MODULE FLASHING" title="Module flashing">Tooling to flash and read out modules straight from the head unit. Right now that’s the Haldex Gen4 and PQ EPS, plus my exhaust valve controller.</PageHead>
  <Note><strong>Module flashing is inherently risky.</strong> It’s difficult to brick a module on these cars beyond recovery, but nothing’s impossible. Flashing is at your own risk. I am not responsible for thermonuclear war, lost bananas, exploded timing chain tensioners, etc. etc.</Note>
  <div className="page-summary"><span>On this page</span><a href="#controllers" onClick={e => { e.preventDefault(); document.getElementById('haldex-tools').scrollIntoView(); }}>Haldex Gen4</a><a href="#controllers" onClick={e => { e.preventDefault(); document.getElementById('eps-tools').scrollIntoView(); }}>PQ EPS</a><a href="#controllers" onClick={e => { e.preventDefault(); document.getElementById('exhaust-tools').scrollIntoView(); }}>Exhaust valve</a></div>
  <Section title="Haldex Gen4" id="haldex-tools"><p><strong>Open:</strong> Diagnostics → AWD → Flash Controller.</p><Figure src="dataview-controller.jpg" caption="Identification, sectors, firmware, then read or flash. Sample identity; no transfer shown."/><Steps items={[
    ['Upload the image', 'Through the file portal (320 KiB .bin). Hit Refresh in the controller tool.'],
    ['Query Controller', 'Reads its identity and picks default sectors.'],
    ['Pick sectors', 'They decide what gets written or read. The tool patches supported images and fixes checksums.'],
    ['Hold to Flash, or Read Controller firmware', 'A readout needs no file. Tap twice to cancel one.'],
  ]}/><p>A readout is only what you selected: unread areas are <code>FF</code>. Keep the BIN with its report (both in the file portal).</p><SourceLink source="references/HALDEX_READOUT.md">Readout details</SourceLink></Section>
  <Section title="PQ EPS steering" id="eps-tools"><p>Mainly for flashing steering datasets, though other regions can be flashed too. <strong>Open:</strong> Diagnostics → Steering Assist → Flash Controller. Same flow as Haldex.</p><Figure src="dataview-eps.jpg" caption="PQ EPS with a sample 4 KiB steering dataset."/><ul>
    <li><strong>4 KiB file:</strong> steering dataset.</li>
    <li><strong>384 KiB image:</strong> full firmware.</li>
    <li><strong>Partial regions</strong> (config or dataset) need the controller to report revision 3000 or newer.</li>
    <li><strong>EEPROM readout</strong> (1 KiB). That’s the EEPROM, not the firmware.</li>
  </ul></Section>
  <Section title="My exhaust valve" id="exhaust-tools"><p>A small one: this is my own valve controller. <strong>Open:</strong> the Exhaust valve controller tile in Diagnostics, or the valve button on the Hudiy bar.</p><Figure src="dataview-exhaust.jpg" caption="Exhaust controller: last request shown as unconfirmed; firmware is separate from Open/Close."/><p><strong>Open / Close</strong> sends the command. The controller remembers its own position, but nothing reports back, so status is always <strong>sent / unconfirmed</strong>.</p><p><strong>Firmware:</strong> upload a ZIP (or the manifest plus both slot images) in the file portal, Refresh, <strong>Validate only</strong> if you want a dry check, then <strong>Update firmware</strong> and confirm.</p><SourceLink source="flasher/EXHAUST_VALVE.md">Bundle and command details</SourceLink></Section>
  <Section title="Flashing Mode stays on"><p>Any controller operation turns on Flashing Mode, which stops this project transmitting on CAN (listening and logging still work). It stays on afterward, through reboots. Turn it off yourself: <strong>Hudiy app menu → Flashing Mode</strong>. It won’t turn off mid-transfer or while a failed Haldex flash still needs recovery.</p><Note>All of this has offline tests; hardware-bench acceptance is still outstanding. Passing validation or a simulated transfer doesn’t prove it works on your controller.</Note><SourceLink source="references/FLASHING_MODE.md">Flashing Mode and recovery</SourceLink></Section>
  <Related links={[[ 'files', 'Upload firmware & download readouts', 'The file portal.' ],['dataview','AWD dashboard','Live Haldex data and modes.']]}/>
</>; }

function Controls() { return <>
  <PageHead location="CONTROLS & BEHAVIOR / INPUTS" title="Buttons & wheel controls">The stock buttons drive Hudiy through key mappings you can change. These are my defaults.</PageHead>
  <Section title="Steering wheel"><Table headings={['Control', 'Press or rotate', 'Hold']} rows={[
    ['Navigation wheel', 'Up: previous track · Down: next track', '—'],
    ['Navigation wheel click', 'Play / pause', 'Play / pause'],
    ['MODE', 'Select', 'Back'],
    ['Voice / PTT', 'Voice assistant', 'Hudiy home'],
    ['Volume wheel and click', 'Car volume; nothing on the Pi', '—'],
  ]}/></Section>
  <Section title="RNS-E faceplate"><p>Click a button to see what it does on press, hold and long hold. Long holds on the track buttons and knob save logs, shut down and reboot the Pi.</p><RnseFaceplate/></Section>
  <Section title="TV panel shortcuts (my firmware)"><p>In TV mode: NAV opens navigation, TEL phone, MEDIA the current player, INFO DataView, CAR RNS-E Manager, NAME the app menu. SETUP goes home. RADIO leaves TV. Which projected app NAV/TEL/MEDIA land on depends on Android Auto/CarPlay.</p></Section>
  <Section title="Wiper stalk: DIS pages"><p>The cluster has its own pages: trip computer 1 and 2, speedo, lap timer, and ours (the center display).</p><ul>
    <li><strong>Reset</strong> (button on the bottom of the stalk): flips between cluster pages.</li>
    <li><strong>Rocker</strong> (end of the stalk): changes what's in the current page. In the trip computer that's its readouts; in ours it cycles our apps (<code>applist</code> order).</li>
  </ul><p>By default ours takes over the center as soon as it starts. With <code>start_inactive</code> on, it waits until you flip to it with Reset.</p><p><code>claim_on_nav</code> / <code>claim_on_phone</code> switch the cluster to our nav or phone page when a route or call starts, and give it back when it ends unless you'd flipped to it yourself. Turning either on also makes ours start inactive.</p></Section>
  <Section title="Give the wheel to the DIS"><p>On a readings page or a call, <strong>double-click MODE</strong> to give the navigation wheel to the DIS. The little wheel icon shows it has it.</p><ul>
    <li><strong>Scroll:</strong> move between items, or pages, or Accept/Reject.</li>
    <li><strong>Click:</strong> do the selected thing.</li>
    <li><strong>Double-click the wheel:</strong> back out (cancel a page change, or go back to the page name / Accept).</li>
    <li><strong>Double-click MODE</strong> or change page with the stalk: normal wheel again.</li>
  </ul><p>Volume is never taken over. If the DIS service dies, the wheel goes back to normal on its own.</p></Section>
  <Section title="Hudiy menu & bar"><p>The installer adds these to Hudiy:</p><ul>
    <li><strong>Bar:</strong> DataView, cycle Haldex mode, toggle the exhaust valve, resume Android Auto.</li>
    <li><strong>App menu:</strong> RNS-E Manager, DataView, Update RNS-E stuff, Update Hudiy (Hudiy itself), Restore Configs, Check Version (shows the installed branch and commit), Save Logs, Toggle Diagnostics, Flashing Mode, reboot and shutdown.</li>
  </ul></Section>
  <Section title="Remap"><p>All of it is in <code>input_mappings</code>: wheel and faceplate short/long presses, and faceplate extended holds. Values are a Linux key (<code>KEY_ENTER</code>), a Hudiy action object, or <code>null</code>. Extended holds can also run a shell command if <code>features.system_actions</code> is on. The stalk just follows the DIS app list.</p></Section>
  <Settings rows={[
    ['input_mappings.mfsw.double_click_ms', 'Double-click window, default 350 ms.'],
    ['input_mappings.mfsw', 'Steering-wheel mappings.'],
    ['input_mappings.mmi', 'Faceplate mappings (short_press / long_press / extended_press).'],
    ['display.phone.scroll_wheel_phone_menu', 'Give calls the wheel automatically.'],
    ['display.center_display.applist', 'Rocker cycle order.'],
    ['display.center_display.start_inactive', 'Wait for Reset instead of taking over the center at startup.'],
  ]}/>
  <Related links={[['readings', 'Readings wheel examples', 'Page select, record, stop, mark.'], ['phone', 'Phone wheel examples', 'Accept / Reject / End Call.']]}/>
</>; }

function Power() { return <>
  <PageHead location="CONTROLS & BEHAVIOR / VEHICLE STATE" title="Connections, appearance & power">The Pi follows the car: phone connection, day/night, clock and shutdown. Each one has its own switch.</PageHead>
  <Section title="Phone reconnect"><ul>
    <li><strong>Ignition on</strong> (or radio on without ignition): Bluetooth and Android Auto are allowed to connect.</li>
    <li><strong>Door open or unlock:</strong> a short connect window (15 s by default) so the phone is ready sooner.</li>
    <li><strong>Ignition/radio off:</strong> disconnect after the delay.</li>
  </ul></Section>
  <Section title="Day/night, source & time"><ul>
    <li><strong>Day/night:</strong> Hudiy follows the headlights, which carries over to Android Auto/CarPlay. <code>sync_android_auto</code> also sets AA’s mode directly.</li>
    <li><strong>Source controls:</strong> pause when you leave the TV source, resume when you come back. Off by default.</li>
    <li><strong>Clock:</strong> sets the Pi’s time from the car when they drift apart. Set your timezone.</li>
    <li><strong>TV simulation:</strong> pretends there’s a TV tuner so the RNS-E offers the TV source.</li>
  </ul></Section>
  <Section title="Shutdown and bus sleep"><ul>
    <li><strong>GPIO shutdown</strong> (my setup): watches the amp-wake pin and shuts down once it’s been off for the delay. Match the pin and polarity to your wiring.</li>
    <li><strong>Ignition/key shutdown:</strong> shuts down after ignition off or key out for the delay. Coming back on cancels it.</li>
    <li><strong>Listen-only CAN:</strong> stops transmitting once the bus is going to sleep, so the Pi doesn’t keep the car awake. Falls back to a timer after ignition off.</li>
  </ul></Section>
  <Settings rows={[
    ['features.power_management.connection_management', 'Reconnect triggers, wake windows, disconnect delay.'],
    ['features.power_management', 'GPIO, ignition shutdown and listen-only.'],
    ['features.day_night_mode', 'Follow the headlights.'],
    ['features.sync_android_auto', 'Also set Android Auto’s day/night.'],
    ['features.source_controls', 'Pause/resume on source change.'],
    ['features.time_sync', 'Clock sync threshold and format.'],
    ['features.car_time_zone', 'Your timezone.'],
  ]}/>
</>; }

function Manager() { return <>
  <PageHead location="SETTINGS & TOOLS / RNS-E MANAGER" title="RNS-E Manager">Settings, services, logs and picture controls, on the head unit. Open it from Hudiy’s app menu or the CAR button. It’s its own service, so it works when DataView is down.</PageHead>
  <Section title="Settings"><p>Pick config.json or one of Hudiy’s five config files, search, edit, save. Same descriptions as the <a href="#configuration">config helper</a>. Saving backs up the old file to <code>~/confbackup/YYYY-MM-DD/N/</code>. If the file changed since you opened it, the save is refused; refresh and redo it. Nothing restarts on its own.</p></Section>
  <Section title="Services and logs"><p><strong>Services:</strong> start, stop or restart any of this project’s services. Stopping CAN transport stops the DIS services too, so start them again after. Services in use by a controller operation are locked.</p><p><strong>Logs:</strong> the last 1–500 journal lines for a service. Follow to keep it updating. Full saved logs are in the <a href="#files">file portal</a>.</p></Section>
  <Section title="RNS-E brightness (my firmware)"><ul>
    <li><strong>Screen brightness (0–10):</strong> the RNS-E brightness setting. Auto follows day/night (default 10 day, 1 night).</li>
    <li><strong>LCD brightness (0–100):</strong> the backlight. Auto has its own day/night values (default 100, 6). 0 follows the cluster.</li>
    <li><strong>Source label:</strong> optionally shows Hudiy, CarPlay or Android Auto on the RNS-E, based on what Hudiy says is playing. It’s not a connection indicator.</li>
  </ul><p>Sliders are for testing live; they don’t switch off auto. Needs <a href="#rnse-firmware">my firmware</a>.</p></Section>
  <Section title="Picture"><p><strong>Pi video:</strong> gamma, contrast, black point and RGB gain on the Pi’s output, live. <strong>Save for startup</strong> keeps it; <strong>Restore original</strong> drops it.</p><p><strong>RNS-E ADC:</strong> tune the RNS-E’s own video input: RGB gain and offset, timing, sync, register dumps, Revert to stock, presets, and an 800 × 480 test image. ADC changes don’t survive a reboot or TV/camera switch, so reload your preset.</p><SourceLink source="hudiy_manager/ADC_TUNING.md">ADC tuning</SourceLink></Section>
  <Related links={[[ 'make-it-yours', 'Settings to change first', 'And where each kind of setting lives.' ],['video-audio','Video setup','HDMI → VGA into the RNS-E.']]}/>
</>; }

function Configuration({ selection, setSelection }) { return <>
  <PageHead location="SETUP / CONFIG.JSON" title="Configuration helper">Edit config.json in your browser, with a description for every setting. DIS pages and recording profiles are edited in DataView, not here.</PageHead>
  <ConfigLaunch selection={selection} setSelection={setSelection}/>
  <Section title="Use it"><Steps items={[
    ['Open or Import', 'Open pulls config.json from the repo/branch above. Import JSON loads your own file; use that to keep your settings.'],
    ['Search and edit', 'Search names, paths, descriptions or values. Bad numbers or JSON block export until fixed.'],
    ['Download and put it on the Pi', <>Upload it in the <a href="#files">file portal</a> (Configuration), or copy it over SSH. Then restart the affected services. See <a href="#apply-update">Apply config & update</a>.</>],
  ]}/><p><strong>Undo load</strong> brings back what you had before the last load. Nothing is written to GitHub. Settings links on the other pages open this helper with that setting searched.</p><p>Unknown or old settings in an import are kept as-is, not migrated.</p></Section>
  <Section title="Where things are"><ul>
    <li><strong>Startup app and stalk order:</strong> Cluster display → Center display</li>
    <li><strong>Navigation pop-ups:</strong> Cluster display → Navigation</li>
    <li><strong>Call page and wheel takeover:</strong> Cluster display → Phone</li>
    <li><strong>Buttons:</strong> Buttons & wheel</li>
    <li><strong>Reconnect and shutdown:</strong> Power & integration</li>
    <li><strong>Upload PIN and firmware folders:</strong> File portal / controller storage</li>
  </ul></Section>
</>; }

function Files() { return <>
  <PageHead location="VEHICLE DATA / FILE PORTAL" title="Files, uploads & logs">A web page on the Pi for your phone or laptop. Upload firmware or a config; download recordings, debug logs and readouts.</PageHead>
  <Figure src="file-portal-overview.jpg" caption="The portal with sample files: recordings, debug logs and controller files, with search and downloads."/>
  <div className="address-panel"><span>OPEN ON YOUR PHONE OR COMPUTER</span><code>http://&lt;Pi-IP&gt;:5003/files</code><p>Replace &lt;Pi-IP&gt; with the Pi’s address.</p></div>
  <Section title="Upload controller firmware"><Figure src="file-portal-upload.jpg" caption="Pick the target, pick the file, validate and save."/><Steps items={[
    ['Controller files → Upload, pick the target', 'Haldex, PQ EPS or Exhaust valve.'],
    ['Pick the file and validate', 'Enter the upload PIN if you set one. Bad files are rejected; existing files aren’t overwritten.'],
    ['Refresh in the controller tool', 'Uploading only stores it. Flashing happens in DataView.'],
  ]}/><ul>
    <li><strong>Haldex Gen4:</strong> 320 KiB .bin.</li>
    <li><strong>PQ EPS:</strong> 384 KiB full image or 4 KiB steering dataset .bin.</li>
    <li><strong>Exhaust valve:</strong> ZIP with can-update.json and both slot images, or those three files separately.</li>
  </ul><p>The PIN only covers uploads. Anyone on the Pi’s network can download.</p></Section>
  <Section title="Replace a config"><p><strong>Configuration</strong> takes config.json or one of Hudiy’s config files and replaces the one on the Pi. The old file is backed up first. Restart the affected services in <a href="#manager">RNS-E Manager</a> (or restart Hudiy for its own configs).</p></Section>
  <Section title="Drive recordings"><p>CSVs from <strong>AWD → Drive Logger</strong>: <strong>Haldex fused</strong> (Haldex data with speed, RPM, steering, braking etc.) or <strong>Raw CAN</strong> (one row per frame). Download one or the whole folder as a ZIP.</p><p>Data & Logs recordings aren’t here; export those from <strong>Review → CSV</strong>.</p><a className="text-button" href="#recordings">Data & Logs recordings →</a></Section>
  <Section title="Debug logs"><Figure src="file-portal-debug.jpg" caption="Debug logs: saved journals, live logs, Hudiy API captures and flash reports."/><Steps items={[
    ['Hit Save Logs right after the problem', 'From the Hudiy menu (or a long hold on the previous-track button). Saves recent journals and Hudiy API captures to a new dated folder.'],
    ['Debug logs → download', 'One collection, or All logs ZIP.'],
    ['Say what you did', 'What you pressed, what was on screen, which call/track/turn. “It did a thing” doesn’t help.'],
  ]}/><ul>
    <li><strong>Service & error logs:</strong> the Save Logs snapshots.</li>
    <li><strong>Live service logs:</strong> current output. RAM only, so grab them before a reboot.</li>
    <li><strong>Hudiy API captures:</strong> always recording; media, nav and phone events.</li>
    <li><strong>Flashing operation logs:</strong> reports from controller operations.</li>
  </ul><Note>API captures can contain street names, contacts and phone numbers. Check before you share them.</Note></Section>
  <Section title="Readouts & ZIPs"><p><strong>Controller files</strong> also has Haldex and EPS readouts with their reports. ZIPs keep folder structure; the default size limit is 256 MiB.</p></Section>
  <Related links={[[ 'controllers', 'Module flashing', 'Query, flash and read out.' ],['recordings','Data & Logs','Profiles, graphs and CSV.']]}/>
</>; }

function Tools() { return <>
  <PageHead location="SETUP / DEVELOPMENT" title="Developer tools">For making cluster artwork, checking text and colors, testing without the car, and digging into CAN data.</PageHead>
  <Section title="Browser helpers"><div className="tool-grid">{[
    ['bitmap_tool.html', 'Bitmap tool', 'Turn a bitmap into icon data for the DIS.'],
    ['audscii_helper.html', 'AUDSCII helper', 'Cluster character encoding and text bytes.'],
    ['theme_viewer.html', 'Theme viewer', 'Paste Hudiy’s light/dark palette to see the color roles.'],
  ].map(([file, title, text]) => <a key={file} className="tool-card" href={`./tools/${file}`} target="_blank" rel="noreferrer"><h3>{title} ↗</h3><p>{text}</p></a>)}</div></Section>
  <Section title="Image & GIF tester"><p>Runs images and GIFs through the real DIS image pipeline. Compare settings, scrub frames, export config snippets.</p><SourceLink source="tools/dis_image_tester/README.md">Run the image tester</SourceLink></Section>
  <Section title="Emulator & bench"><p>The browser DIS emulator draws with the real cluster fonts, so you can check layouts without sitting in the car. The bench console drives a real cluster on the desk.</p><SourceLink source="dis_emulator/bench_cluster/README.md">Bench console</SourceLink></Section>
  <Section title="CAN tools"><ul>
    <li><code>process_dumps.py</code>: strip known traffic from a candump and show what changes.</li>
    <li><code>tp2/status_tp2_logger.py</code> + <code>can_decoder_pro.py</code>: log measuring groups and correlate them with CAN bytes.</li>
    <li><code>inspect_measuring_groups.py</code>: look at group responses.</li>
    <li><code>dhu_driver.py</code>: drive the Android Auto DHU with WASD to test navigation at your desk.</li>
  </ul><SourceLink source="tools/README.md">Tool commands</SourceLink><SourceLink source="vehicle_data/CATALOG.md">Value catalog</SourceLink></Section>
  <Section title="Leftovers"><p>The old <code>car_widget/</code> boost and car-art widgets are still in the repo, but nothing installs or opens them.</p><p>Openpilot has a DIS app, but its transport is hard-disabled because its CAN IDs clash with Haldex. Turning the config key on does nothing.</p></Section>
  <Related links={[[ 'configuration', 'Configuration helper', 'Edit config.json.' ],['files','File portal','Downloads, uploads and captures.']]}/>
</>; }

export const Pages = { overview: Overview, readings: Readings, navigation: Navigation, media: Media, phone: Phone, acceleration: Acceleration, 'top-display': TopDisplay, dataview: Dashboards, recordings: Recordings, diagnostics: Diagnostics, controllers: Controllers, controls: Controls, power: Power, manager: Manager, configuration: Configuration, files: Files, tools: Tools, ...GetStartedPages, ...HowToPages };
