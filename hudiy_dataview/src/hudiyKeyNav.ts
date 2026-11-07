/**
 * Knob and button input for Hudiy web apps.
 *
 * Hudiy reports key input through callbacks on window.hudiy and leaves the
 * highlight to the page. The highlight is an attribute, not DOM focus: focusing
 * a TouchTextInput opens the keyboard, which must wait for a press.
 *
 * Page markup can use:
 *   data-key-back    RETURN clicks this control. Dialogs without one keep RETURN.
 *   data-key-scroll  A pane with no controls. The knob scrolls it, then moves on.
 *   data-key-skip    Never highlight this control.
 */
export interface HudiyInput {
  inputFocus?: boolean;
  activated?: boolean;
  onInputFocusChanged?: () => void;
  onActivatedChanged?: () => void;
  onMoveToNextControl?: () => boolean;
  onMoveToPreviousControl?: () => boolean;
  onTriggered?: () => void;
  onGoLeft?: () => void;
  onGoRight?: () => void;
  onGoBack?: () => boolean;
}

export interface KeyNavOptions {
  root: HTMLElement;
  hudiy: HudiyInput;
  /** Long press of the track buttons. */
  onTab?: (delta: 1 | -1) => void;
  /** Where the highlight lands after onTab. */
  activeTab?: string;
}

/** Sent by useHudiyTheme, which owns hudiy.onAttached. */
const HUDIY_ATTACHED_EVENT = 'hudiy-attached';
/** Asks a text field to open its keyboard. focus() fires no event unless the page has system focus. */
export const KEY_ACTIVATE_EVENT = 'key-activate';

const CONTROLS = 'button, a[href], select, input:not([type="hidden"]):not([type="file"]), textarea, summary, [data-key-scroll]';
const BUTTON_LIKE = new Set(['checkbox', 'radio', 'button', 'submit', 'reset', 'color']);
/** A longer jump than this would skip text, so the pane scrolls first. */
const PAGE = 0.7;
const MARGIN = 8;
/** Lets React commit before the highlight looks for what a press opened. */
const SETTLE_MS = 60;
/** Knob ticks closer than this count as a fast turn on a wide slider. */
const FAST_TICK_MS = 120;
const STYLE_ID = 'hudiy-key-nav-style';
const STYLE = `[data-key-focus]{outline:3px solid var(--primary,#ff3b3b)!important;outline-offset:-3px!important}
[data-key-focus="edit"]{box-shadow:0 0 0 4px var(--primary,#ff3b3b)!important}`;

type Control = HTMLElement & { disabled?: boolean };
type Editing = { element: HTMLInputElement | HTMLSelectElement; start: string };

const isDisabled = (element: Control) => element.disabled === true || element.getAttribute('aria-disabled') === 'true';
const isSelect = (element: Element): element is HTMLSelectElement => element.tagName === 'SELECT';
const inputType = (element: Element) => element.tagName === 'INPUT' ? ((element as HTMLInputElement).type || 'text') : null;
const isRange = (element: Element): element is HTMLInputElement => inputType(element) === 'range';
const isScrollPane = (element: Element) => element.hasAttribute('data-key-scroll');
const isText = (element: Element) => element.tagName === 'TEXTAREA' || (inputType(element) !== null && !BUTTON_LIKE.has(inputType(element) as string) && !isRange(element));

function isReachable(element: Control) {
  if (element.closest('[inert]') || element.closest('[aria-hidden="true"]') || element.hasAttribute('data-key-skip')) return false;
  if (element.getAttribute('tabindex') === '-1' || !element.getClientRects().length) return false;
  if (getComputedStyle(element).visibility === 'hidden') return false;
  // Closed <details> content can still report boxes. Its own summary stays reachable.
  const closed = element.closest('details:not([open])');
  if (closed && !(element.tagName === 'SUMMARY' && element.parentElement === closed)) return false;
  return !isScrollPane(element) || element.scrollHeight > element.clientHeight + 1;
}

const scrollsOn = (element: Element, axis: 'overflowX' | 'overflowY') => /auto|scroll/.test(getComputedStyle(element)[axis]);

function scrollParent(element: Element): HTMLElement | null {
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (scrollsOn(parent, 'overflowY') && parent.scrollHeight > parent.clientHeight + 1) return parent;
  }
  return null;
}

/** Only real scroll panes move. scrollIntoView could shift DataView's overflow:hidden tab strip. */
function reveal(element: Element, root: Element) {
  for (let parent = element.parentElement; parent && parent !== root.parentElement; parent = parent.parentElement) {
    const box = parent.getBoundingClientRect(), own = element.getBoundingClientRect();
    if (scrollsOn(parent, 'overflowY')) {
      if (own.top < box.top) parent.scrollTop -= box.top - own.top + MARGIN;
      else if (own.bottom > box.bottom) parent.scrollTop += own.bottom - box.bottom + MARGIN;
    }
    if (scrollsOn(parent, 'overflowX')) {
      if (own.left < box.left) parent.scrollLeft -= box.left - own.left + MARGIN;
      else if (own.right > box.right) parent.scrollLeft += own.right - box.right + MARGIN;
    }
  }
}

function pageScroll(pane: HTMLElement, delta: 1 | -1) {
  const room = delta > 0 ? pane.scrollHeight - pane.clientHeight - pane.scrollTop : pane.scrollTop;
  if (room < 1) return false;
  pane.scrollTop += delta * Math.min(room, Math.max(40, pane.clientHeight * PAGE));
  return true;
}

function setRangeValue(element: HTMLInputElement, value: string) {
  // React tracks the instance's value, so this has to use the prototype setter.
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
}

function setSelectValue(element: HTMLSelectElement, value: string) {
  element.value = value;
  element.dispatchEvent(new Event('change', { bubbles: true }));
}

/** TEMPORARY: bench probe for Up/Down. Remove with /api/manage/key-nav-probe. */
function probe(message: string) {
  console.error(`[key-nav] ${message}`);
  void fetch('/api/manage/key-nav-probe', { method: 'POST', headers: { 'X-Hudiy-Management': '1', 'Content-Type': 'text/plain' }, body: `${window.location.port} ${message}`, keepalive: true }).catch(() => undefined);
}

export function installHudiyKeyNav({ root, hudiy, onTab, activeTab }: KeyNavOptions): () => void {
  let current: Control | null = null;
  let scope: Element = root;
  let lastIndex = 0;
  let editing: Editing | null = null;
  let lastTick = 0;
  let path: Element[] = [];
  let handedOff: 0 | 1 | -1 = 0;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const remembered = new WeakMap<Element, Control>();

  const live = () => !!hudiy.inputFocus && !!hudiy.activated;
  const paint = () => {
    if (!current) return;
    if (live()) current.setAttribute('data-key-focus', editing?.element === current ? 'edit' : 'true');
    else current.removeAttribute('data-key-focus');
  };
  const setCurrent = (next: Control | null) => {
    if (next !== current) current?.removeAttribute('data-key-focus');
    current = next;
    if (next) {
      // Saved now: a removed control can't name its old parents afterwards.
      path = [];
      for (let parent = next.parentElement; parent && parent !== root; parent = parent.parentElement) path.push(parent);
    }
    paint();
  };
  const activeScope = () => {
    // The whole document: the flasher portals itself to <body>, outside root.
    const open = Array.from(document.querySelectorAll<HTMLElement>('[aria-modal="true"]')).filter(element => !element.closest('[inert]') && element.getClientRects().length > 0);
    return open[open.length - 1] ?? root;
  };
  const controls = () => Array.from(scope.querySelectorAll<Control>(CONTROLS)).filter(isReachable);
  /** When the highlighted control is gone, stay in the closest section that still exists. */
  const nearest = () => {
    const list = controls().filter(element => !isDisabled(element));
    for (const section of path) {
      if (!section.isConnected) continue;
      const found = list.find(element => section.contains(element));
      if (found) return found;
    }
    return list[0] ?? null;
  };
  const syncScope = () => {
    const next = activeScope();
    if (next === scope) return;
    if (current) remembered.set(scope, current);
    scope = next;
    const back = remembered.get(next);
    lastIndex = 0;
    setCurrent(back?.isConnected ? back : null);
  };
  const later = (callback: () => void) => {
    const timer = setTimeout(() => { timers.delete(timer); callback(); }, SETTLE_MS);
    timers.add(timer);
  };
  /** A press can open or close a dialog, so the highlight follows on the next commit. */
  const settle = () => {
    if (editing && (!editing.element.isConnected || editing.element.disabled)) endEdit(true);
    syncScope();
    if (live()) {
      if (!current?.isConnected) setCurrent(nearest());
      paint();
      if (current) reveal(current, root);
    } else paint();
  };

  const beginEdit = (element: HTMLInputElement | HTMLSelectElement) => {
    editing = { element, start: element.value };
    lastTick = 0;
    element.focus({ preventScroll: true });
    // The sliders hold their draft from keydown, so polling can't overwrite it.
    if (isRange(element)) element.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true }));
    paint();
  };
  function endEdit(commit: boolean) {
    if (!editing) return;
    const { element, start } = editing;
    editing = null;
    if (!commit && element.value !== start) {
      if (isRange(element)) setRangeValue(element, start); else setSelectValue(element as HTMLSelectElement, start);
    }
    if (isRange(element)) element.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    element.blur();
    paint();
  }
  const adjust = ({ element }: Editing, delta: 1 | -1) => {
    if (isSelect(element)) {
      for (let index = element.selectedIndex + delta; index >= 0 && index < element.options.length; index += delta) {
        if (element.options[index].disabled) continue;
        setSelectValue(element, element.options[index].value);
        return;
      }
      return;
    }
    const min = Number(element.min || 0), max = Number(element.max || 100), step = Number(element.step) || 1;
    const now = Date.now();
    const multiplier = (max - min) / step > 40 && now - lastTick < FAST_TICK_MS ? 5 : 1;
    lastTick = now;
    const next = Math.max(min, Math.min(max, Number(element.value) + delta * step * multiplier));
    setRangeValue(element, String(Number(next.toFixed(6))));
  };

  const move = (delta: 1 | -1): boolean => {
    if (!live()) return true;
    if (editing) { adjust(editing, delta); return true; }
    syncScope();
    if (current && !current.isConnected) {
      setCurrent(nearest());
      if (current) reveal(current, root);
      return true;
    }
    const modal = scope !== root;
    const list = controls();
    if (current && isScrollPane(current) && pageScroll(current, delta)) return true;
    const known = current ? list.indexOf(current) : -1;
    const anchor = known >= 0 ? known : Math.min(lastIndex, list.length) - delta;
    let target: Control | undefined;
    for (let index = anchor + delta; index >= 0 && index < list.length; index += delta) {
      if (!isDisabled(list[index])) { target = list[index]; lastIndex = index; break; }
    }
    if (target) {
      handedOff = 0;
      const pane = scrollParent(target);
      if (pane) {
        const box = pane.getBoundingClientRect(), own = target.getBoundingClientRect();
        const beyond = delta > 0 ? own.bottom - box.bottom : box.top - own.top;
        if (beyond > pane.clientHeight * PAGE && pageScroll(pane, delta)) return true;
      }
      setCurrent(target);
      reveal(target, root);
      return true;
    }
    const pane = current && scrollParent(current);
    if (pane && pageScroll(pane, delta)) return true;
    // Hudiy cycles focus back in without saying which way. A second push the same
    // way means it came round, so start over instead of handing off again forever.
    const cycled = handedOff === delta;
    if (!modal && !cycled) { handedOff = delta; return false; }
    handedOff = 0;
    // In a dialog, Hudiy's next scope is behind it, so the knob always stays inside.
    const enabled = list.filter(element => !isDisabled(element));
    if (enabled.length) { setCurrent(delta > 0 ? enabled[0] : enabled[enabled.length - 1]); reveal(current as Control, root); }
    return true;
  };

  const trigger = () => {
    if (!live()) return;
    if (editing) { endEdit(true); return; }
    syncScope();
    if (!current?.isConnected) { settle(); return; }
    if (isDisabled(current) || isScrollPane(current)) return;
    if (isRange(current) || isSelect(current)) { beginEdit(current as HTMLInputElement | HTMLSelectElement); return; }
    if (isText(current) && !(current as HTMLInputElement).readOnly) current.dispatchEvent(new Event(KEY_ACTIVATE_EVENT));
    else current.click();
    later(settle);
  };

  const back = (): boolean => {
    if (editing) { endEdit(false); return true; }
    syncScope();
    const control = Array.from(scope.querySelectorAll<Control>('[data-key-back]')).find(element => isReachable(element) && !isDisabled(element));
    if (control) { control.click(); later(settle); return true; }
    return scope !== root;
  };

  const tab = (delta: 1 | -1) => {
    if (!live()) return;
    if (editing) { adjust(editing, delta); return; }
    syncScope();
    if (scope !== root || !onTab) return;
    onTab(delta);
    later(() => {
      const active = activeTab ? root.querySelector<Control>(activeTab) : null;
      if (active) { setCurrent(active); reveal(active, root); } else settle();
    });
  };

  const focusChanged = () => {
    if (!live()) endEdit(true);
    settle();
  };

  const handlers: HudiyInput = {
    onInputFocusChanged: focusChanged,
    onActivatedChanged: focusChanged,
    onMoveToNextControl: () => move(1),
    onMoveToPreviousControl: () => move(-1),
    onTriggered: trigger,
    onGoLeft: () => tab(-1),
    onGoRight: () => tab(1),
    onGoBack: back,
  };
  const names = Object.keys(handlers) as (keyof typeof handlers & `on${string}`)[];
  const previous = new Map(names.map(name => [name, hudiy[name]]));
  const target = hudiy as Record<string, unknown>;
  for (const name of names) {
    const handler = handlers[name] as () => boolean | void;
    target[name] = () => {
      const result = handler();
      probe(`${name} -> ${result} focus=${hudiy.inputFocus} activated=${hudiy.activated} on=${current?.getAttribute('aria-label') || current?.textContent?.slice(0, 24) || current?.tagName || 'none'}`);
      return result;
    };
  }

  const attached = () => {
    probe(`attached ${Object.keys(hudiy).filter(key => key !== 'colorScheme').sort().join(',')}`);
    settle();
  };
  const keydown = (event: KeyboardEvent) => { if (event.isTrusted) probe(`keydown ${event.key} on ${(event.target as Element | null)?.tagName}`); };
  window.addEventListener(HUDIY_ATTACHED_EVENT, attached);
  document.addEventListener('keydown', keydown, true);
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = STYLE;
    document.head.appendChild(style);
  }
  // Remounting can miss onAttached; Hudiy has already set these if it has attached.
  settle();

  return () => {
    timers.forEach(clearTimeout);
    endEdit(true);
    current?.removeAttribute('data-key-focus');
    window.removeEventListener(HUDIY_ATTACHED_EVENT, attached);
    document.removeEventListener('keydown', keydown, true);
    document.getElementById(STYLE_ID)?.remove();
    for (const name of names) target[name] = previous.get(name);
  };
}
