import { useState, useCallback } from 'react';
import { useSocket } from './hooks/useSocket';
import { useSwipe } from './hooks/useSwipe';
import { TabId } from './types';
import { EngineTab } from './tabs/EngineTab';
import { TransmissionTab } from './tabs/TransmissionTab';
import { AWDTab } from './tabs/AWDTab';

const TABS: { id: TabId; label: string }[] = [
  { id: 'engine', label: 'Engine' },
  { id: 'transmission', label: 'Transmission' },
  { id: 'awd', label: 'AWD' },
];

export function App() {
  const [currentTab, setCurrentTab] = useState<TabId>('engine');
  const [smoothing, setSmoothing] = useState(true);
  const { data, intervalMs, socket } = useSocket(currentTab);

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



  return (
    <div className="container">
      <nav className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn${currentTab === tab.id ? ' active' : ''}`}
            onClick={() => setCurrentTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
        <button
          className={`smooth-toggle${smoothing ? ' active' : ''}`}
          onClick={toggleSmoothing}
          title="Toggle data smoothing"
        >
          ~
        </button>
      </nav>

      <div
        className="tab-swipe-area"
        style={{ '--rx-interval': `${intervalMs}ms` } as React.CSSProperties}
        {...swipeHandlers}
      >
        <div
          className="tab-strip"
          style={{ transform: `translateX(${translatePct}%)` }}
        >
          <div className="tab-slide"><EngineTab data={data} /></div>
          <div className="tab-slide"><TransmissionTab data={data} /></div>
          <div className="tab-slide"><AWDTab data={data} /></div>
        </div>
      </div>
    </div>
  );
}
