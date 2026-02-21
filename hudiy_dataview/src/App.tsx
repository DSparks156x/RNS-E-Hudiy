import { useState } from 'react';
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
  const { data, intervalMs } = useSocket(currentTab);

  const currentIndex = TABS.findIndex((t) => t.id === currentTab);

  const goNext = () => {
    if (currentIndex < TABS.length - 1) setCurrentTab(TABS[currentIndex + 1].id);
  };
  const goPrev = () => {
    if (currentIndex > 0) setCurrentTab(TABS[currentIndex - 1].id);
  };

  const swipeHandlers = useSwipe({ onSwipeLeft: goNext, onSwipeRight: goPrev });

  // Each tab is 1/TABS.length of the strip width; slide by that many tab-widths
  const tabCount = TABS.length;
  const translatePct = -(currentIndex * (100 / tabCount));

  // Get window resolution for debugging
  const [resolution, setResolution] = useState({
    wInner: window.innerWidth,
    hInner: window.innerHeight,
    wOuter: window.outerWidth,
    hOuter: window.outerHeight
  });

  import('react').then(React => {
    React.useEffect(() => {
      const handleResize = () => {
        setResolution({
          wInner: window.innerWidth,
          hInner: window.innerHeight,
          wOuter: window.outerWidth,
          hOuter: window.outerHeight,
        });
      };
      window.addEventListener('resize', handleResize);
      return () => window.removeEventListener('resize', handleResize);
    }, []);
  });

  return (
    <div className="container">
      {/* Debug Resolution Overlay */}
      <div style={{
        position: 'fixed',
        top: '10px',
        left: '10px',
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        color: 'white',
        padding: '10px 20px',
        borderRadius: '5px',
        zIndex: 9999,
        pointerEvents: 'none',
        fontSize: '18px',
        fontWeight: 'bold',
        textShadow: '1px 1px 2px black'
      }}>
        <div>Window: {resolution.wOuter}x{resolution.hOuter}</div>
        <div>Viewport: {resolution.wInner}x{resolution.hInner}</div>
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
          <div className="tab-slide"><EngineTab data={data} /></div>
          <div className="tab-slide"><TransmissionTab data={data} /></div>
          <div className="tab-slide"><AWDTab data={data} /></div>
        </div>
      </div>
    </div>
  );
}

