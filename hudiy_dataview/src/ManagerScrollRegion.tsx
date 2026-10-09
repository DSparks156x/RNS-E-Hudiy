import { ReactNode, useEffect, useRef, useState } from 'react';

/** Visible controls remain usable when the host browser has no touch panning. */
export function ManagerScrollRegion({ children }: { children: ReactNode }) {
  const region = useRef<HTMLDivElement>(null);
  const pane = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [state, setState] = useState({ overflow: false, up: false, down: false });
  useEffect(() => {
    const update = () => {
      if (!pane.current || !region.current || !content.current) return;
      const node = pane.current;
      const next = { overflow: content.current.scrollHeight > region.current.clientHeight + 1, up: node.scrollTop > 1, down: node.scrollTop + node.clientHeight < node.scrollHeight - 1 };
      setState(previous => Object.keys(next).every(key => next[key as keyof typeof next] === previous[key as keyof typeof next]) ? previous : next);
    };
    const resize = new ResizeObserver(update);
    [region.current, pane.current, content.current].forEach(node => { if (node) resize.observe(node); });
    pane.current?.addEventListener('scroll', update); update();
    const node = pane.current;
    return () => { resize.disconnect(); node?.removeEventListener('scroll', update); };
  }, []);
  const scroll = (direction: number) => { if (pane.current) pane.current.scrollTop += direction * Math.max(80, pane.current.clientHeight * .75); };
  return <div className="manager-settings-region" ref={region}><main className="manager-settings-scroll" ref={pane}><div className="manager-scroll-content" ref={content}>{children}</div></main>{state.overflow && <nav className="manager-scroll-buttons" aria-label="Scroll settings"><button type="button" disabled={!state.up} onClick={() => scroll(-1)}>↑ Scroll up</button><button type="button" disabled={!state.down} onClick={() => scroll(1)}>↓ Scroll down</button></nav>}</div>;
}
