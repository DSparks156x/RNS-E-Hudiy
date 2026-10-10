import React from 'react';
import { Note, PageHead, Related, Section, Settings, SourceLink, Steps, Table, Todo } from './ui';
import { Command } from './HowToGuides';
import './get-started.css';

export const getStartedGroups = [
  { id: 'hw', title: 'SETUP', subtitle: 'Hardware & firmware' },
  { id: 'sw', title: 'SETUP', subtitle: 'Hudiy & this project' },
];
export const getStartedTopics = [
  { id: 'hardware', group: 'hw', title: 'What you need', icon: '▣', summary: 'The reference build: RNS-E 193, Pi 5, CAN, video and audio', keywords: 'parts shopping list bill of materials CarPiHat Pro 5 FiiO KA11 DAC HDMI VGA sync combiner Raspberry Pi 5 193 TT' },
  { id: 'can-bus', group: 'hw', title: 'CAN connections', icon: '⇄', summary: 'Fault-tolerant ICAN, plus optional OBD CAN', keywords: 'fault tolerant low speed ISO 11898-3 TJA1055 MCP2515 100 kbit gateway diagnostics second interface can0 candump' },
  { id: 'video-audio', group: 'hw', title: 'Video & audio', icon: '▭', summary: 'HDMI → VGA with sync combining, 480p and the DAC', keywords: 'RGB sync combiner VGA HDMI 800x480 480p TV input video in motion ADC FiiO KA11 audio' },
  { id: 'rnse-firmware', group: 'hw', title: 'RNS-E firmware', icon: '◈', summary: 'What the head unit firmware must do, and the options', keywords: 'video in motion VIM DIS FIS redirect PCBBC firmware 480p brightness PTT lower buttons TV' },
  { id: 'my-firmware', group: 'hw', title: 'Install my firmware', icon: '↯', summary: 'Back up, flash and check the RNS-E firmware', keywords: 'flash RNS-E firmware backup revert install' },
  { id: 'install-hudiy', group: 'sw', title: 'Install Hudiy', icon: '◐', summary: 'Prepare the Pi and get Hudiy on the RNS-E screen first', keywords: 'Hudiy Raspberry Pi OS install image Android Auto CarPlay screen' },
  { id: 'install-package', group: 'sw', title: 'Install this project', icon: '↓', summary: 'Run the installer and choose the update channel', keywords: 'install.sh update_rnse.sh branch testing main release beta first install' },
  { id: 'configure', group: 'sw', title: 'Configure CAN, video & audio', icon: '⚙', summary: 'The guided setup script for your hardware', keywords: 'setup script guided CAN interface ICAN OBD video display audio DAC config.json' },
  { id: 'installed', group: 'sw', title: 'What got installed', icon: '☷', summary: 'Services, folders, ports and backups', keywords: 'systemd services ports 5003 5004 RAM disk config.json confbackup sudoers folders' },
  { id: 'make-it-yours', group: 'sw', title: 'Make it yours', icon: '✎', summary: 'The settings almost everyone changes, and where they live', keywords: 'settings high_resolution applist GPIO shutdown units Manager config' },
];

// Placeholders are marked with <Todo>; they render as visible to-do boxes until filled in.

function Hardware() { return <>
  <PageHead location="SETUP / HARDWARE" title="What you need">This is my setup: an Audi TT with the white cluster and an RNS-E 193. Other cars and parts can work, but this is what the project is developed and tested on.</PageHead>
  <Section title="My setup"><Table headings={['Part', 'What I use', 'Notes']} rows={[
    ['Head unit', 'RNS-E 193 (800 × 480)', <>Needs modified firmware: see <a href="#rnse-firmware">RNS-E firmware</a>. My firmware doesn't support the 192; PCBBC's does.</>],
    ['Instrument cluster', 'TT white cluster', <>Red clusters should work, but are untested. Set <code>display.center_display.high_resolution</code> to match your cluster.</>],
    ['Computer', 'Raspberry Pi 5 (2 GB), official Pi 5 active cooler', ''],
    ['Storage', '256 GB NVMe', 'Not required, but it boots very, very fast. An SD card works.'],
    ['CAN interface', 'CarPiHat Pro 5', <>Any SocketCAN interface with a <strong>fault-tolerant</strong> transceiver. See <a href="#can-bus">CAN connections</a>.</>],
    ['Video', 'HDMI → VGA adapter + sync combiner', <>Into the RNS-E's TV/RGB input. See <a href="#video-audio">Video & audio</a>.</>],
    ['Audio', 'FiiO KA11 USB DAC', <>The CarPiHat's audio has a lot of ringing; the KA11 is much better. <Todo inline>where the audio goes into the car</Todo></>],
    ['Power & wake', 'CarPiHat Pro 5, woken by the amp-wake signal', "Amp wake comes on when the car is unlocked or a door opens, so the Pi starts booting before the ignition is on. The CarPiHat's 5 V rail is noisy and weak; see below."],
  ]}/></Section>
  <Section title="About the CarPiHat Pro 5"><p>It looked really appealing to combine power, CAN and audio into one board. It's good at CAN.</p><p><strong>Power:</strong> it sucks ass. It's rather noisy, with a weak 5 V rail. Not having a dedicated CAN-woken MCU to manage power means weird caveats with Pi shutdown.</p><p><strong>Audio:</strong> also sucks ass. It's got a lot of ringing. The FiiO KA11 was 30 bucks and is much better.</p><p>Quite a letdown.</p><Todo>Alternatives worth trying, and the shutdown caveats in detail.</Todo></Section>
  <Section title="Wiring overview"><Todo>Diagram or table: Pi/HAT ↔ RNS-E connector pins (CAN, video, audio, amp wake, power), with photos if possible.</Todo></Section>
  <Related links={[[ 'can-bus', 'CAN connections', 'Fault-tolerant ICAN, plus optional OBD CAN.' ],['rnse-firmware','RNS-E firmware','What the head unit must allow before any of this works.']]}/>
</>; }

function CanBus() { return <>
  <PageHead location="SETUP / HARDWARE / CAN" title="CAN connections">You need a fault-tolerant SocketCAN interface on ICAN. For diagnostics, you may also need a high-speed interface on OBD CAN.</PageHead>
  <Section title="What you need"><ul>
    <li><strong>ICAN (required):</strong> a SocketCAN interface with a fault-tolerant transceiver, connected at the RNS-E.</li>
    <li><strong>OBD CAN (for diagnostics):</strong> a SocketCAN interface with a high-speed transceiver. Not required on more permissive gateways that allow diagnostics from ICAN.</li>
  </ul><p>Fault-tolerant and high-speed transceivers aren't interchangeable. Each one only works on its own kind of bus.</p></Section>
  <Section title="Permissive gateways"><p>Some gateways pass diagnostic requests from ICAN through to the other modules, and some don't. For example, the 1K0 907 530 AD (SW 0233) in my 2010 TT does, while the gateway in a tester's 2011 A3 didn't. If yours doesn't, you need OBD CAN for diagnostics.</p><p>This affects more than fault codes. Only some live data comes straight off ICAN; a lot of it comes from diagnostics. If the DIS works but most dashboard values and fault reads never answer, the gateway is probably blocking diagnostics.</p></Section>
  <Section title="Set it up"><p>The guided setup script configures your CAN interfaces after the project is installed. See <a href="#configure">Configure CAN, video & audio</a>.</p></Section>
  <Related links={[[ 'video-audio', 'Video & audio', 'Getting the Pi onto the RNS-E screen.' ]]}/>
</>; }

function VideoAudio() { return <>
  <PageHead location="SETUP / HARDWARE / VIDEO" title="Video & audio">The Pi's HDMI output is converted to VGA, its sync signals are combined, and the result goes into the RNS-E's TV input at 800 × 480.</PageHead>
  <Section title="Video path"><Steps items={[
    ['HDMI → VGA adapter', 'A cheap active adapter turns the Pi\'s HDMI into analog RGB with separate horizontal and vertical sync.'],
    ['Sync combiner', 'The RNS-E input expects one combined sync signal. A small circuit merges H and V sync before the RNS-E.'],
    ['RNS-E TV / RGB input', 'With my firmware the input runs at 480p, so the Pi\'s 800 × 480 desktop maps to the screen without scaling.'],
  ]}/><Todo>Sync combiner schematic or part, the adapter model used, and the connector/pinout at the RNS-E.</Todo></Section>
  <Section title="Pi display settings"><p>The <code>example_config.txt</code> and <code>example_cmdline.txt</code> files in the repository come from the upstream project's composite-video setup. They don't match this build.</p><p>The guided setup script sets up the display: see <a href="#configure">Configure CAN, video & audio</a>.</p></Section>
  <Section title="Picture tuning"><p>Once there's a picture, the <a href="#manager">RNS-E Manager</a> can adjust the Pi's gamma, contrast, black level and RGB gains. My firmware also improves the head unit's own video quality.</p></Section>
  <Section title="Audio"><p>Audio comes from a FiiO KA11 USB DAC rather than the Pi's own output.</p><Todo>Where the DAC output connects (RNS-E TV audio input, AUX or other).</Todo><p>The guided setup script selects the audio output.</p></Section>
  <Related links={[[ 'rnse-firmware', 'RNS-E firmware', 'Video in motion and 480p input.' ]]}/>
</>; }

function RnseFirmware() { return <>
  <PageHead location="SETUP / FIRMWARE" title="RNS-E firmware">Stock RNS-E firmware won't work with this project. At minimum, the head unit has to show video while driving and stop driving the DIS itself so the Pi can take it over.</PageHead>
  <Section title="What the firmware must do"><Table headings={['Requirement', 'Why']} rows={[
    ['Video in motion', 'Stock firmware blanks the TV input while the car is moving.'],
    ['DIS IDs redirected', "The RNS-E normally writes its own content to the cluster. With its DIS messages redirected, the Pi's DIS services can use the cluster instead."],
  ]}/></Section>
  <Section title="Firmware options"><Table headings={['Feature', 'PCBBC firmware', 'My firmware']} rows={[
    ['RNS-E 192 support', 'Yes', 'No (193 only)'],
    ['Video in motion', 'Yes', 'Yes'],
    ['DIS IDs redirected', 'FIS-control option', 'Yes, by default'],
    ['480p video input', '—', 'Yes'],
    ['Improved video quality', '—', 'Yes'],
    ['Screen and LCD brightness control from the Pi', '—', 'Yes'],
    ['Steering-wheel PTT button', '—', 'Yes'],
    ['Lower RNS-E buttons (TV panel shortcuts)', '—', 'Yes'],
  ]}/><p>Several features of this project only work with my firmware: the <a href="#controls">TV panel shortcuts</a>, the brightness controls in RNS-E Manager, and the wheel's voice button.</p><Todo>How the PCBBC FIS-control option is set up for this project, and anything else my firmware adds.</Todo></Section>
  <Section title="Which should I use?"><p>Use my firmware if you have a 193 and want everything on this site to work. PCBBC firmware covers the basics, but 480p, brightness, PTT and the lower buttons won't be available. If you have a 192, PCBBC is the option: my firmware doesn't support it.</p><a className="text-button inline-link" href="#my-firmware">Install my firmware →</a></Section>
  <Related links={[[ 'my-firmware', 'Install my firmware', 'Back up, flash and verify.' ],['controls','Buttons & wheel','What each faceplate and wheel button does.']]}/>
</>; }

function MyFirmware() { return <>
  <PageHead location="SETUP / FIRMWARE / INSTALL" title="Install my firmware">How to back up the head unit, flash my firmware, check that it worked, and go back to stock.</PageHead>
  <Note>Flashing the head unit can leave it unusable if something goes wrong. Keep a backup of the original firmware before you start.</Note>
  <Section title="Compatibility"><Todo>Which RNS-E part numbers, hardware versions and software versions my firmware supports.</Todo></Section>
  <Section title="What you need"><Todo>Tools, cables, media (CD/SD) and where to get the firmware file.</Todo></Section>
  <Section title="Back up the original"><Todo>Steps to read and keep the stock firmware.</Todo></Section>
  <Section title="Flash the firmware"><Todo>Flashing steps.</Todo></Section>
  <Section title="Check that it worked"><Todo>Version screen/check, then: video while moving, DIS left free for the Pi, TV panel buttons sending 0x461 frames (visible in candump).</Todo></Section>
  <Section title="Go back to stock"><Todo>Revert steps.</Todo></Section>
  <Related links={[[ 'rnse-firmware', 'Firmware options', 'What my firmware adds compared with PCBBC firmware.' ],['install-hudiy','Next: install Hudiy','Get the Pi onto the screen.']]}/>
</>; }

function InstallHudiy() { return <>
  <PageHead location="SETUP / SOFTWARE / HUDIY" title="Install Hudiy">Hudiy is the head-unit software this project builds on. It provides Android Auto, CarPlay, media and the app menu. Install it and get it on the RNS-E screen before adding this project.</PageHead>
  <Steps items={[
    ['Prepare the Pi', <Todo inline>OS image and version, first-boot settings, username (the installer assumes the account's home is /home/&lt;user&gt;).</Todo>],
    ['Install Hudiy', <>Follow the upstream instructions in the <a href="https://github.com/wiboma/hudiy" target="_blank" rel="noreferrer">Hudiy repository ↗</a>.</>],
    ['Get it on the RNS-E screen', 'Select TV on the RNS-E. Hudiy should fill the screen at 800 × 480. Fix the picture now: it is much easier to debug video before the CAN services are running.'],
    ['Connect your phone once', 'Pair the phone and start Android Auto or CarPlay so you know projection works without this project in the way.'],
  ]}/>
  <Todo>Hudiy licence/activation notes and any Hudiy settings this project depends on.</Todo>
  <Related links={[[ 'install-package', 'Next: install this project', 'One command, then choose the update channel.' ]]}/>
</>; }

function InstallPackage() { return <>
  <PageHead location="SETUP / SOFTWARE / INSTALL" title="Install this project">The installer downloads the project, installs its dependencies and services, and merges its settings into Hudiy's configs. Afterward, the setup script configures CAN, video and audio for your hardware.</PageHead>
  <Note>Back up your SD card or drive first, or install onto a fresh one. The installer changes Hudiy's config files (with backups) and installs system services.</Note>
  <Section title="Choose a channel"><Table headings={['Channel', 'What you get']} rows={[
    [<code>main</code>, 'The main branch.'],
    [<code>testing</code>, 'The latest development work. May be broken at any moment.'],
    [<><code>release</code> / <code>beta</code></>, 'The newest matching release-* or beta-* tag, or the branch of that name if there is no tag.'],
  ]}/><p>Whatever channel you choose now is saved in <code>~/config.json</code> as <code>branch</code>, and later updates follow it.</p></Section>
  <Section title="Run the installer"><p>Download the installer from the channel you want, then pass the same channel name to it. This example installs <code>testing</code>:</p><Command>{'cd ~\nwget -O install.sh https://raw.githubusercontent.com/DSparks156x/RNS-E-Hudiy/testing/install.sh\nsudo bash ./install.sh testing'}</Command><p>On a first install, always give the channel name. With no <code>~/config.json</code> yet, the installer otherwise uses <code>main</code>. If the requested branch or tag doesn't exist, it also falls back to <code>main</code>, so check the <strong>Install Branch/Tag</strong> line it prints.</p><p>When it finishes, it asks whether to reboot. Say yes.</p></Section>
  <Section title="Updating later"><p>After the first install, update from the Hudiy app menu or with:</p><Command>{'sudo ~/hudiy_client/update_rnse.sh'}</Command><p>The updater reads <code>repo</code> and <code>branch</code> from <code>~/config.json</code>. Unlike the first install, it cancels if that branch or tag doesn't exist. It reboots when finished.</p><a className="text-button inline-link" href="#apply-update">Updates, backups and restoring configs →</a></Section>
  <SourceLink source="install.sh">Installer</SourceLink><SourceLink source="hudiy_client/update_rnse.sh">Updater</SourceLink>
  <Related links={[[ 'configure', 'Next: configure CAN, video & audio', 'The guided setup script.' ],['installed','What got installed','Services, folders and ports.']]}/>
</>; }

function Configure() { return <>
  <PageHead location="SETUP / SOFTWARE / CONFIGURE" title="Configure CAN, video & audio">A guided script sets up the Pi for your hardware and updates <code>config.json</code> to match. Run it after installing the project, and again whenever you change hardware.</PageHead>
  <Todo>The command to run the script.</Todo>
  <Section title="What it asks about"><ul>
    <li><strong>CAN:</strong> your ICAN interface, and an optional OBD CAN interface. See <a href="#can-bus">CAN connections</a>.</li>
    <li><strong>Video:</strong> the Pi display output for the RNS-E. See <a href="#video-audio">Video & audio</a>.</li>
    <li><strong>Audio:</strong> which output to use, such as a USB DAC.</li>
  </ul><Todo>The actual prompts and options, what each one writes (system files and config.json keys), and whether it reboots.</Todo></Section>
  <Section title="Check CAN"><p>With the ignition on, you should see a steady stream of frames:</p><Command>{'candump can0'}</Command></Section>
  <Related links={[[ 'installed', 'What got installed', 'Services, folders and ports.' ]]}/>
</>; }

function Installed() { return <>
  <PageHead location="SETUP / SOFTWARE / INSTALLED" title="What got installed">Everything runs as systemd services under your user account, one job each.</PageHead>
  <Section title="Services"><Table headings={['Service', 'Job', 'Depends on']} rows={[
    [<code>can_handler</code>, 'The only process that talks to the CAN interface; shares frames with the other services.', 'can0'],
    [<code>can_base_function</code>, 'TV-tuner presence, time sync, RNS-E brightness bridge and ADC commands.', 'can_handler'],
    [<code>can_keyboard_control</code>, 'Turns RNS-E, TV-panel and wheel buttons into Hudiy key presses; decides who owns the wheel.', 'can_handler'],
    [<code>dark_mode_api</code>, 'Follows the car\'s lights for Hudiy\'s day/night mode.', 'can_handler'],
    [<code>hudiy_data_api</code>, 'Reads media, navigation and phone data from Hudiy and records API captures.', 'can_handler'],
    [<code>dis_service</code>, 'The cluster (DIS) driver. Waits 10 s after start.', 'can_handler'],
    [<code>dis_display</code>, 'Draws the center-display apps: readings, navigation, media, phone. Also waits 10 s.', 'dis_service'],
    [<code>dis_top_display</code>, 'The two top lines of the cluster.', 'can_handler'],
    [<code>tp2_worker</code>, 'Diagnostic (TP2.0) sessions: measuring groups, fault codes.', 'can0'],
    [<code>hudiy_status_service</code>, 'Named vehicle values from passive CAN and diagnostics.', 'tp2_worker, can_handler'],
    [<code>hudiy_dataview</code>, 'DataView touchscreen, Data & Logs recorder and the file portal (port 5003).', 'tp2_worker'],
    [<code>hudiy_manager</code>, 'RNS-E Manager: settings, services, logs, picture and ADC controls (port 5004).', 'network'],
    [<code>haldex_manager</code>, 'Haldex Gen4 mode requests.', 'can_handler'],
  ]}/><p>Check them all at once:</p><Command>{'systemctl --no-pager status "can_*" "dis_*" "hudiy_*" tp2_worker haldex_manager dark_mode_api'}</Command></Section>
  <Section title="Files and folders"><Table headings={['Path', 'Contents']} rows={[
    [<code>~/config.json</code>, 'Project settings. Edit in RNS-E Manager or the config helper.'],
    [<code>~/rns-e_can, ~/dis_client, ~/hudiy_client, ~/hudiy_dataview, ~/hudiy_manager, ~/vehicle_data, ~/tp2, ~/flasher</code>, 'Project code. Replaced on update; don\'t keep your own files here.'],
    [<code>~/.hudiy/share/config/*.json</code>, 'Hudiy configs. The installer adds this project\'s apps, shortcuts and actions.'],
    [<code>~/logs/data-logs/</code>, 'DIS pages, recording profiles and saved recordings.'],
    [<code>~/haldexfw, ~/epsfw, ~/exhaustfw</code>, 'Controller firmware libraries and readouts.'],
    [<code>~/confbackup/YYYY-MM-DD/N/</code>, 'Copies of configs from before each change the installer or Manager made.'],
    [<code>/var/log/rnse_control, /run/rnse_control</code>, 'RAM disks for live logs and runtime state. Cleared on reboot.'],
  ]}/></Section>
  <Section title="Network addresses"><Table headings={['Address', 'What']} rows={[
    [<code>http://&lt;Pi-IP&gt;:5003/files</code>, 'File portal, from your phone or computer.'],
    [<code>http://localhost:5003</code>, 'DataView (opened from Hudiy).'],
    [<code>http://localhost:5004</code>, 'RNS-E Manager (opened from Hudiy).'],
  ]}/></Section>
  <Section title="System changes"><p>The installer adds your user to the <code>input</code> and <code>bluetooth</code> groups, enables <code>uinput</code> for virtual key presses, and installs a limited sudoers rule (<code>/etc/sudoers.d/rnse-manager</code>) so RNS-E Manager can start, stop and restart only this project's services.</p></Section>
  <Related links={[[ 'troubleshooting', 'Find the broken bit', 'Which service to check for each symptom.' ]]}/>
</>; }

function MakeItYours() { return <>
  <PageHead location="SETUP / SOFTWARE / SETTINGS" title="Make it yours">The defaults match my car. These are the ones you'll probably change first. Edit them in RNS-E Manager on the head unit, or with the config helper.</PageHead>
  <Settings rows={[
    ['display.center_display.high_resolution', 'On for a white DIS, off for a red one.'],
    ['display.center_display.applist', 'Which apps the stalk rocker cycles through, in order.'],
    ['display.units.speed', 'Imperial, metric, or follow the car.'],
    ['features.power_management', 'GPIO shutdown pin and polarity for your wake wiring, and shutdown delays.'],
    ['features.car_time_zone', 'Your timezone, for setting the Pi clock from the car.'],
    ['input_mappings', 'What the wheel and faceplate buttons do.'],
  ]}/>
  <Section title="Which settings belong where?"><Table headings={['You want to change…', 'Edit here']} rows={[
    ['DIS app order, navigation, phone takeover, buttons, power', <>RNS-E Manager → Settings, or the <a href="#configuration">config helper</a></>],
    ['DIS reading pages, units/icons/precision, linked recordings', 'DataView → Data & Logs → DIS pages'],
    ['Values in a named recording', 'DataView → Data & Logs → Record → Choose values'],
    ['ECU measuring groups shown', 'DataView → Diagnostics → selected module'],
    ['Screen colours and RNS-E brightness', <><a href="#manager">RNS-E Manager</a> → RNS-E</>],
    ['Firmware files for module flashing', <><a href="#files">File portal</a> → Upload</>],
    ['Replace a whole config file from your phone', <><a href="#files">File portal</a> → Configuration</>],
  ]}/><p>Neither Manager nor the portal restarts anything. Restart the affected services from Manager → Services.</p></Section>
  <Related links={[[ 'apply-update', 'Apply config & update', 'Restart the right services after a change.' ],['configuration','Configuration helper','Full settings reference.']]}/>
</>; }

export const GetStartedPages = {
  hardware: Hardware,
  'can-bus': CanBus,
  'video-audio': VideoAudio,
  'rnse-firmware': RnseFirmware,
  'my-firmware': MyFirmware,
  'install-hudiy': InstallHudiy,
  'install-package': InstallPackage,
  configure: Configure,
  installed: Installed,
  'make-it-yours': MakeItYours,
};
