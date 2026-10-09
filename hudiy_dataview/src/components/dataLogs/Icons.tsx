import { disIconPixels } from './disPixelAssets';

const paths: Record<string, React.ReactNode> = {
  engine: <><path d="M6 8h10l3 4h3v7h-4l-2 2H7l-2-3H2v-7h4zM8 5h6M11 5v3" /><path d="M9 12h5v5H9z" /></>,
  temperature: <><path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0zM12 8v9M17 6h3M17 10h2" /></>,
  boost: <><circle cx="12" cy="12" r="9" /><path d="m12 12 5-5M5 12h2M12 5v2M17 12h2M8 19h8" /></>,
  fuel: <><path d="M4 21V4h9v17M4 11h9M2 21h13M14 7h2l3 3v8a2 2 0 0 0 4 0v-6l-4-5M19 10h3" /></>,
  oil: <><path d="m3 11 4-2 7 2 4-4 3 2-5 7H7l-4-5zM8 9V6h6M21 15s-2 2-2 3a2 2 0 0 0 4 0c0-1-2-3-2-3z" /></>,
  voltage: <><path d="M3 7h18v13H3zM6 4v3M18 4v3M6 13h5M8.5 10.5v5M15 13h3" /></>,
  speed: <><path d="M3 18a10 10 0 1 1 18 0M12 15l5-7M4 12h2M7 6l1 2M12 3v3M18 6l-1 2M18 12h2" /><circle cx="12" cy="15" r="2" /></>,
  rpm: <><path d="M4 17a9 9 0 1 1 16 0M12 13l6-4M6 7l2 2M12 4v3M5 13h2M17 13h2M7 21h10" /><circle cx="12" cy="13" r="2" /></>,
  gear: <><path d="m9 3-.7 3-3 1-2.5-1.5-2 3L3 11v3l-2 2.5 2 3L6 18l3 1 1 3h4l1-3 3-1 2.5 1.5 2-3L21 14v-3l2-2.5-2-3L18 7l-3-1-.7-3z" /><circle cx="12" cy="12" r="4" /></>,
  awd: <><path d="M6 5h12M6 19h12M12 5v14M3 2h3v6H3zM18 2h3v6h-3zM3 16h3v6H3zM18 16h3v6h-3z" /><path d="m12 9 3 3-3 3-3-3z" /></>,
  brake: <><circle cx="12" cy="12" r="7" /><path d="M3 6a11 11 0 0 0 0 12M21 6a11 11 0 0 1 0 12M12 7v6M12 16v1" /></>,
  steering: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="2" /><path d="M3 10h7M14 10h7M12 14v7" /></>,
  lambda: <path d="M6 3h5l8 18M11 8 4 21M19 21h3" />,
  cool: <><path d="M10 13V4a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0zM12 6v10M2 22l3-2 3 2 4-2 4 2 3-2 3 2" /></>,
  intake: <><rect x="14" y="4" width="7" height="16" rx="1" /><path d="M18 7v10M2 12h11M8 8l4 4-4 4" /></>,
  flow: <path d="M2 7h18l-4-4M20 7l-4 4M2 17h18l-4-4M20 17l-4 4" />,
  ambient: <><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></>,
  pressure: <><circle cx="12" cy="10" r="8" /><path d="m12 10 4-4M12 18v4M8 22h8M6 10h2M12 4v2" /></>,
  torque: <><path d="M19 9a8 8 0 1 0 0 7M20 3v6h-6M12 9v13" /><circle cx="12" cy="11" r="2" /></>,
  exhaust: <><rect x="6" y="4" width="12" height="10" rx="2" /><path d="M2 9h4M18 9h4M9 7l2 2-2 2M15 7l-2 2 2 2M3 19q3-4 6 0t6 0t6 0" /></>,
  clutch: <><path d="M8 3v18M16 3v18M5 6v12M19 6v12M2 10v4M22 10v4M11 5v14M13 5v14" /></>,
  pump: <><circle cx="12" cy="10" r="7" /><path d="M2 8h3v4H2zM19 8h3v4h-3zM9 17v4M15 17v4M6 21h12m-9-15 6 4-6 4z" /></>,
  inject: <><path d="M12 2v4M7 6h10v7H7zM12 13v5M7 17l-2 4M17 17l2 4M12 20v2" /></>,
  timing: <><circle cx="12" cy="13" r="8" /><path d="M9 2h6M12 2v3M12 8v5l4 2M18 5l2-2" /></>,
  distance: <path d="m7 2-5 20M17 2l5 20M12 3v3M12 10v3M12 17v4" />,
  level: <><path d="M4 3v18h16V3M4 12q4-4 8 0t8 0M4 16h16M4 19h16" /></>,
  status: <><rect x="3" y="3" width="18" height="18" rx="1" /><path d="m6 12 4 4 8-9" /></>,
  fan: <><circle cx="12" cy="12" r="2" /><path d="M10 10C3 6 6 0 11 3l2 7M14 10c4-7 10-4 7 1l-7 2M14 14c7 4 4 10-1 7l-2-7M10 14c-4 7-10 4-7-1l7-2" /></>,
  spark: <path d="m14 2-9 12h7l-2 8 9-12h-7z" />,
  valve: <><path d="M7 3h10M12 3v6M2 8l10 7L2 22zM22 8l-10 7 10 7z" /></>,
  target: <><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2" /><path d="M12 1v5M12 18v5M1 12h5M18 12h5" /></>,
  back: <path d="m14 5-7 7 7 7" />, check: <path d="m4 12 5 5L20 6" />,
  add: <path d="M12 4v16M4 12h16" />, record: <circle cx="12" cy="12" r="7" fill="currentColor" stroke="none" />,
  stop: <path d="M5 5h14v14H5z" fill="currentColor" stroke="none" />, marker: <path d="M5 22V3h14l-3 5 3 5H5" />,
  chart: <path d="M3 3v18h18M5 16l5-6 4 3 7-9" />, pages: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
  search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 6 6" /></>, chevron: <path d="m9 5 7 7-7 7" />,
};
paths.air = paths.flow;
paths.ignition = paths.spark;
paths.current = paths.spark;
export const slotIcons = ['auto', 'engine', 'rpm', 'speed', 'temperature', 'cool', 'oil', 'intake',
  'ambient', 'boost', 'flow', 'pressure', 'fuel', 'pump', 'inject', 'lambda', 'exhaust',
  'spark', 'timing', 'gear', 'clutch', 'awd', 'torque', 'voltage', 'current', 'steering',
  'brake', 'fan', 'valve', 'distance', 'level', 'status', 'target',
  'throttle', 'pedal', 'sparkplug', 'camshaft', 'piston', 'wheel', 'abs', 'traction',
  'compressor', 'heater', 'door', 'hood', 'lights', 'wiper', 'parking', 'seatbelt'];
const iconLabels: Record<string, string> = { auto: 'Automatic', cool: 'Coolant', gear: 'Gearbox',
  inject: 'Injection', flow: 'Airflow', rpm: 'RPM', awd: 'AWD', spark: 'Ignition',
  sparkplug: 'Spark plug', camshaft: 'Camshaft', abs: 'ABS', seatbelt: 'Seat belt' };
export const iconLabel = (name: string) => iconLabels[name] || name;
export function DISIcon({ name, size = 28 }: { name: string; size?: number }) {
  const pixels = disIconPixels[name] || disIconPixels.engine;
  return <svg width={size} height={size} viewBox="0 0 14 14" fill="currentColor" shapeRendering="crispEdges" aria-hidden="true"><path transform={`translate(2 ${Math.floor((14-pixels.height)/2)})`} d={pixels.path} /></svg>;
}
export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  if (!paths[name] && disIconPixels[name]) return <DISIcon name={name} size={size} />;
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.engine}</svg>;
}
