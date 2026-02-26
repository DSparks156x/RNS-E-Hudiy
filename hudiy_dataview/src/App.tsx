import { useState, useCallback } from 'react';
import { useSocket } from './hooks/useSocket';
import { useSwipe } from './hooks/useSwipe';
import { TabId } from './types';
import { EngineTab } from './tabs/EngineTab';
import { TransmissionTab } from './tabs/TransmissionTab';
import { AWDTab } from './tabs/AWDTab';
import { DiagnosticsTab } from './tabs/DiagnosticsTab';

import { useHudiyTheme } from './hooks/useHudiyTheme';

const TABS: { id: TabId; label: string }[] = [
  { id: 'engine', label: 'Engine' },
  { id: 'transmission', label: 'Transmission' },
  { id: 'awd', label: 'AWD' },
  { id: 'diagnostics', label: 'Diagnostics' },
];

export function App() {
  const [currentTab, setCurrentTab] = useState<TabId>('engine');
  const [smoothing, setSmoothing] = useState(true);

  // Notice we only get the socket instance back now; data state is gone!
  const { socket } = useSocket(currentTab);

  const themeHook = useHudiyTheme(socket);
  const theme = themeHook.theme;

  // Toggle smoothing on the server — app.py handles the 20Hz interpolation loop
  const toggleSmoothing = useCallback(() => {
    setSmoothing((s) => {
      const next = !s;
      socket?.emit('set_smoothing', { enabled: next });
      return next;
    });
  }, [socket]);

  const currentIndex = TABS.findIndex((t) => t.id === currentTab);

  const goNext = () => {
    if (currentIndex < TABS.length - 1) setCurrentTab(TABS[currentIndex + 1].id);
  };
  const goPrev = () => {
    if (currentIndex > 0) setCurrentTab(TABS[currentIndex - 1].id);
  };

  const swipeHandlers = useSwipe({ onSwipeLeft: goNext, onSwipeRight: goPrev });

  const tabCount = TABS.length;
  const translatePct = -(currentIndex * (100 / tabCount));

  // Convert theme object to CSS variables dynamically
  const themeVars = Object.entries(theme).reduce((acc, [key, value]) => {
    if (typeof value === 'string') {
      // e.g. primaryContainer -> --primary-container
      const cssKey = `--${key.replace(/([A-Z])/g, '-$1').toLowerCase()}`;
      acc[cssKey] = value;
    }
    return acc;
  }, {} as Record<string, string>);


  return (
    <div
      className="container"
      data-theme={theme.darkThemeEnabled ? 'dark' : 'light'}
      style={themeVars as React.CSSProperties}
    >
      <nav className="tabs">
        <button
          className={`smooth-toggle${smoothing ? ' active' : ''}`}
          onClick={toggleSmoothing}
          title="Toggle data smoothing"
        >
          ~
        </button>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn${currentTab === tab.id ? ' active' : ''}`}
            onClick={() => setCurrentTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <div
        className="tab-swipe-area"
        {...swipeHandlers}
      >
        <div
          className="tab-strip"
          style={{ transform: `translateX(${translatePct}%)` }}
        >
          {/* We no longer need to pass the giant data object to components */}
          <div className="tab-slide"><EngineTab /></div>
          <div className="tab-slide"><TransmissionTab /></div>
          <div className="tab-slide"><AWDTab /></div>
          <div className="tab-slide"><DiagnosticsTab isActive={currentTab === 'diagnostics'} /></div>
        </div>
      </div>
    </div>
  );
}
