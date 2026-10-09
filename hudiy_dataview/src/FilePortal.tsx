import { CSSProperties, useEffect, useState } from 'react';
import { HudiyColorScheme, useHudiyTheme } from './hooks/useHudiyTheme';
import { FilesTab, FilesTabProps } from './tabs/FilesTab';
import './portal.css';
interface FilePortalProps extends FilesTabProps { previewTheme?: HudiyColorScheme; }
export function FilePortal({ previewTheme, ...filesProps }: FilePortalProps = {}) {
  const { theme: nativeTheme } = useHudiyTheme(null);
  const [serverTheme, setServerTheme] = useState<HudiyColorScheme | null>(null);
  useEffect(() => {
    if (previewTheme || window.hudiy) return;
    let alive = true;
    const update = async () => {
      try {
        const response = await fetch('/api/files/theme');
        if (!response.ok) return;
        const data: { theme?: HudiyColorScheme } = await response.json();
        if (alive && data.theme) setServerTheme(data.theme);
      } catch { /* Offline palettes retain the last applied values. */ }
    };
    void update();
    const interval = window.setInterval(() => void update(), 30000);
    return () => { alive = false; window.clearInterval(interval); };
  }, [previewTheme]);
  const theme = previewTheme || (window.hudiy ? nativeTheme : serverTheme || nativeTheme);
  const vars = Object.fromEntries(Object.entries(theme).filter(([, value]) => typeof value === 'string')
    .map(([key, value]) => [`--${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`, value]));
  useEffect(() => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (theme.background) meta?.setAttribute('content', theme.background);
  }, [theme]);
  return <div className="container portal-container" data-theme={theme.darkThemeEnabled ? 'dark' : 'light'} style={vars as CSSProperties}><FilesTab {...filesProps} /></div>;
}
