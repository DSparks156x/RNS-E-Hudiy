import { ReactNode } from 'react';

/** Drag to scroll: touch pans natively; mouse-like touch drivers use managerPointerScroll. */
export function ManagerScrollRegion({ children }: { children: ReactNode }) {
  return <div className="manager-settings-region"><main className="manager-settings-scroll"><div className="manager-scroll-content">{children}</div></main></div>;
}
