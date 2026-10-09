/** Some head-unit touch drivers send mouse pointers instead of touch gestures. */
export function installManagerPointerScroll(root: HTMLElement): () => void {
  let gesture: { id: number; x: number; y: number; left: number; top: number; target: Element; pane: HTMLElement | null; axis: 'x' | 'y' | null } | null = null;
  let suppressClickUntil = 0;
  const down = (event: PointerEvent) => {
    suppressClickUntil = 0;
    if (gesture && root.hasPointerCapture(gesture.id)) root.releasePointerCapture(gesture.id);
    gesture = null;
    if (event.pointerType !== 'mouse' || event.button !== 0 || !event.isPrimary) return;
    const target = event.target;
    if (!(target instanceof Element) || target.closest('input, textarea, select, .osk-shade')) return;
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, left: 0, top: 0, target, pane: null, axis: null };
  };
  const move = (event: PointerEvent) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
    if (!gesture.axis) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 8) return;
      const axis = Math.abs(dy) >= Math.abs(dx) ? 'y' : 'x';
      let pane = gesture.target.closest<HTMLElement>('*');
      while (pane && pane !== root) {
        const style = getComputedStyle(pane);
        if (axis === 'y' ? /auto|scroll/.test(style.overflowY) && pane.scrollHeight > pane.clientHeight + 1 : /auto|scroll/.test(style.overflowX) && pane.scrollWidth > pane.clientWidth + 1) break;
        pane = pane.parentElement;
      }
      if (!pane || pane === root) { gesture = null; return; }
      gesture.axis = axis; gesture.pane = pane; gesture.left = pane.scrollLeft; gesture.top = pane.scrollTop;
      root.setPointerCapture(event.pointerId);
    }
    event.preventDefault();
    if (gesture.pane) {
      if (gesture.axis === 'y') gesture.pane.scrollTop = gesture.top - dy;
      else gesture.pane.scrollLeft = gesture.left - dx;
    }
  };
  const end = (event: PointerEvent) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    if (gesture.axis) {
      suppressClickUntil = performance.now() + 500;
      if (root.hasPointerCapture(event.pointerId)) root.releasePointerCapture(event.pointerId);
    }
    gesture = null;
  };
  const click = (event: MouseEvent) => {
    // Keyboard/assistive clicks (detail=0) always retain their normal action.
    if (event.detail && performance.now() < suppressClickUntil) { event.preventDefault(); event.stopImmediatePropagation(); }
  };
  root.addEventListener('pointerdown', down, true);
  root.addEventListener('pointermove', move, true);
  root.addEventListener('pointerup', end, true);
  root.addEventListener('pointercancel', end, true);
  root.addEventListener('click', click, true);
  return () => {
    if (gesture && root.hasPointerCapture(gesture.id)) root.releasePointerCapture(gesture.id);
    root.removeEventListener('pointerdown', down, true);
    root.removeEventListener('pointermove', move, true);
    root.removeEventListener('pointerup', end, true);
    root.removeEventListener('pointercancel', end, true);
    root.removeEventListener('click', click, true);
  };
}
