import { useState } from 'react';
import { useSocket } from './hooks/useSocket';
import { useSwipe } from './hooks/useSwipe';
import { useSmoothedData } from './hooks/useSmoothedData';
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
  const [smoothing, setSmoothing] = useState(false);
  const { data, intervalMs } = useSocket(currentTab);

  // Interpolate data at 60fps between server updates when smoothing is enabled
  const displayData = useSmoothedData(data, intervalMs, smoothing);

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
    <div className="container" style={{ position: 'relative' }}>

      {/* Dev Overlays */}
      <div className="dev-overlay-480" style={{
        position: 'absolute',
        top: 0, left: 0,
        width: '800px', height: '480px',
        border: '2px dashed cyan',
        pointerEvents: 'none',
        zIndex: 9999,
        boxSizing: 'border-box'
      }}>
        <span style={{ color: 'cyan', position: 'absolute', bottom: 2, right: 4, fontSize: '12px', background: 'rgba(0,0,0,0.5)', padding: '0 4px' }}>800x480 (Total Window)</span>
      </div>

      <div className="dev-overlay-406" style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '800px', height: '406px',
        border: '2px dashed magenta',
        pointerEvents: 'none',
        zIndex: 9998,
        boxSizing: 'border-box'
      }}>
        <span style={{ color: 'magenta', position: 'absolute', bottom: 2, right: 4, fontSize: '12px', background: 'rgba(0,0,0,0.5)', padding: '0 4px' }}>800x406 (Viewport Content)</span>
      </div>

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
        {/* Smoothing Toggle — sits flush right in nav bar */}
        <button
          className={`smooth-toggle${smoothing ? ' active' : ''}`}
          onClick={() => setSmoothing((s) => !s)}
          title="Toggle data smoothing"
        >
          ~
        </button>
      </nav>

      {/* Swipe capture area — clips the strip */}
      <div
        className="tab-swipe-area"
        style={{ '--rx-interval': `${intervalMs}ms` } as React.CSSProperties}
        {...swipeHandlers}
      >
        <div
          className="tab-strip"
          style={{ transform: `translateX(${translatePct}%)` }}
        >
          <div className="tab-slide"><EngineTab data={displayData} /></div>
          <div className="tab-slide"><TransmissionTab data={displayData} /></div>
          <div className="tab-slide"><AWDTab data={displayData} /></div>
        </div>
      </div>
    </div>
  );
}
