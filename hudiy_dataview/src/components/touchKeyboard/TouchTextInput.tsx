import { InputHTMLAttributes, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { backspace, insertText, moveCaret, TextEdit } from './editing';
import './touchKeyboard.css';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & {
  value: string;
  onValueChange: (value: string) => void;
  capitalize?: boolean;
  touchOnly?: boolean;
  keyboardLayout?: 'hex';
  formatOnCommit?: (value: string) => string;
};

const letters = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm'].map(row => [...row]);
const symbols = [
  [['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'], ['_', '-', '/', '(', ')', ':', '@', '&', '+', '='], ['.', ',', '?', '!', "'", '"', '#', '%']],
  [['[', ']', '{', '}', '<', '>', '\\', '|', '~', '`'], ['€', '$', '£', '¥', '°', '²', '^', '*', ';', '_'], [':', '/', '-', '+', '=', '&', '@', '%']],
];

function BackspaceIcon() {
  return <svg width="27" height="22" viewBox="0 0 27 22" aria-hidden="true"><path d="M9 3h15v16H9l-7-8zM12 7l8 8M20 7l-8 8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>;
}

function KeyboardDialog({ initial, title, maxLength, password, numeric, capitalize, hex, onCancel, onDone }: {
  initial: string; title: string; maxLength?: number; password: boolean; numeric: boolean; capitalize: boolean;
  hex: boolean;
  onCancel: () => void; onDone: (value: string) => void;
}) {
  const [edit, setEdit] = useState<TextEdit>({ value: initial, start: initial.length, end: initial.length });
  const [shift, setShift] = useState<'off' | 'once' | 'locked'>(capitalize && !initial ? 'once' : 'off');
  const [numbers, setNumbers] = useState(numeric);
  const [symbolPage, setSymbolPage] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const value = useRef(initial);
  const repeat = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stopRepeat = () => { if (repeat.current !== null) clearTimeout(repeat.current); repeat.current = null; };
  useEffect(() => stopRepeat, []);
  useLayoutEffect(() => {
    input.current?.focus({ preventScroll: true });
    input.current?.setSelectionRange(edit.start, edit.end);
  }, [edit]);
  const currentEdit = (): TextEdit => ({ value: value.current,
    start: input.current?.selectionStart ?? value.current.length,
    end: input.current?.selectionEnd ?? value.current.length });
  const apply = (next: TextEdit) => { value.current = next.value; setEdit(next); };
  const type = (character: string) => {
    apply(insertText(currentEdit(), character, maxLength));
    if (!numbers && shift === 'once') setShift('off');
  };
  const erase = () => apply(backspace(currentEdit()));
  const beginErase = () => {
    stopRepeat(); erase();
    const again = () => { erase(); repeat.current = setTimeout(again, 75); };
    repeat.current = setTimeout(again, 400);
  };
  const rows = numbers ? symbols[symbolPage] : letters;
  const key = (character: string) => {
    const text = !numbers && shift !== 'off' ? character.toUpperCase() : character;
    return <button type="button" className="osk-key" key={character} onClick={() => type(text)}>{text}</button>;
  };
  const eraseKey = <button type="button" className="osk-key osk-wide" aria-label="Backspace" onPointerDown={beginErase} onPointerUp={stopRepeat} onPointerCancel={stopRepeat} onPointerLeave={stopRepeat} onClick={event => { if (event.detail === 0) erase(); }}><BackspaceIcon /></button>;
  return <div className="osk-shade" onPointerDown={event => event.stopPropagation()} onPointerUp={event => event.stopPropagation()}>
    <div ref={dialog} className="osk-dialog" role="dialog" aria-modal="true" aria-label={`Keyboard: ${title}`} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); onCancel(); }
      else if (event.key === 'Enter' && event.target === input.current) { event.preventDefault(); onDone(value.current); }
      else if (event.key === 'Tab') {
        const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input') || []);
        const index = items.indexOf(document.activeElement as HTMLElement);
        if ((event.shiftKey && index <= 0) || (!event.shiftKey && index === items.length - 1)) {
          event.preventDefault(); items[event.shiftKey ? items.length - 1 : 0]?.focus();
        }
      }
    }}>
      <div className="osk-heading"><button type="button" className="osk-action" onClick={onCancel}>Cancel</button><div className="osk-title"><strong>{title}</strong><small>{hex ? 'Hex bytes · 0–9, A–F' : maxLength !== undefined ? `${edit.value.length} / ${maxLength}` : 'Touch keyboard'}</small></div><button type="button" className="osk-action osk-done" onClick={() => onDone(value.current)}>Done</button></div>
      <div className="osk-entry" onPointerDown={event => { if (event.target instanceof Element && event.target.closest('button')) event.preventDefault(); }}>
        <input ref={input} type={password ? 'password' : 'text'} aria-label="Keyboard text" inputMode="none" autoComplete="off" spellCheck={false} maxLength={maxLength} value={edit.value} onChange={event => {
          const element = event.target; value.current = element.value;
          setEdit({ value: element.value, start: element.selectionStart ?? element.value.length, end: element.selectionEnd ?? element.value.length });
        }} />
        <button type="button" className="osk-action" onClick={() => apply({ value: value.current, start: 0, end: value.current.length })}>Select all</button>
        <button type="button" className="osk-action" disabled={!edit.value} onClick={() => apply({ value: '', start: 0, end: 0 })}>Clear</button>
      </div>
      <div className="osk-keys" onPointerDown={event => event.preventDefault()}>
        {hex ? <><div className="osk-row">{[...'0123456789'].map(key)}</div><div className="osk-row">{[...'ABCDEF'].map(key)}{eraseKey}</div><div className="osk-row osk-bottom"><button type="button" className="osk-key osk-space" aria-label="Space" onClick={() => type(' ')}>byte space</button><button type="button" className="osk-key osk-cursor" aria-label="Move cursor left" onClick={() => apply(moveCaret(currentEdit(), -1))}>‹</button><button type="button" className="osk-key osk-cursor" aria-label="Move cursor right" onClick={() => apply(moveCaret(currentEdit(), 1))}>›</button></div></> : <><div className="osk-row">{rows[0].map(key)}</div>
        <div className="osk-row osk-middle">{rows[1].map(key)}</div>
        <div className="osk-row"><button type="button" className={`osk-key osk-wide ${(!numbers && shift !== 'off') || (numbers && symbolPage) ? 'active' : ''}`} aria-label={numbers ? 'More symbols' : 'Shift'} aria-pressed={numbers ? symbolPage === 1 : shift !== 'off'} onClick={() => numbers ? setSymbolPage(page => 1 - page) : setShift(previous => previous === 'off' ? 'once' : previous === 'once' ? 'locked' : 'off')}>{numbers ? (symbolPage ? '123' : '#+=') : shift === 'locked' ? 'CAPS' : '⇧'}</button>{rows[2].map(key)}<button type="button" className="osk-key osk-wide" aria-label="Backspace" onPointerDown={beginErase} onPointerUp={stopRepeat} onPointerCancel={stopRepeat} onPointerLeave={stopRepeat} onClick={event => { if (event.detail === 0) erase(); }}><BackspaceIcon /></button></div>
        <div className="osk-row osk-bottom"><button type="button" className="osk-key osk-mode" aria-label={numbers ? 'Letters' : 'Numbers and symbols'} onClick={() => setNumbers(previous => !previous)}>{numbers ? 'ABC' : '?123'}</button><button type="button" className="osk-key osk-punctuation" onClick={() => type(',')}>,</button><button type="button" className="osk-key osk-space" aria-label="Space" onClick={() => type(' ')}>space</button><button type="button" className="osk-key osk-punctuation" onClick={() => type('.')}>.</button><button type="button" className="osk-key osk-cursor" aria-label="Move cursor left" onClick={() => apply(moveCaret(currentEdit(), -1))}>‹</button><button type="button" className="osk-key osk-cursor" aria-label="Move cursor right" onClick={() => apply(moveCaret(currentEdit(), 1))}>›</button></div></>}
      </div>
    </div>
  </div>;
}

/** Explicit controlled text entry; existing diagnostic keypads stay independent. */
export function TouchTextInput({ value, onValueChange, capitalize = false, touchOnly = false, keyboardLayout, formatOnCommit, ...props }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const skipFocus = useRef(false);
  const useBuiltIn = !touchOnly || !!window.hudiy || window.matchMedia('(any-pointer: coarse)').matches;
  const open = (element: HTMLInputElement | null, touch = false) => {
    if (props.disabled || props.readOnly || host || (!useBuiltIn && !touch)) return;
    // React autoFocus can run before the ref attaches. The focus event already
    // has the mounted element, including its enclosing Hudiy theme container.
    setHost(element?.closest<HTMLElement>('.container, .portal-container') || document.body);
  };
  const close = () => {
    setHost(null);
    requestAnimationFrame(() => {
      skipFocus.current = true;
      input.current?.focus({ preventScroll: true });
      skipFocus.current = false;
    });
  };
  useEffect(() => {
    if (!host) return undefined;
    const behind = input.current?.closest<HTMLElement>('[role="dialog"]');
    if (!behind) return undefined;
    const wasInert = behind.inert;
    behind.inert = true;
    return () => { behind.inert = wasInert; };
  }, [host]);
  const title = props['aria-label'] || props.placeholder || 'Enter text';
  return <><input {...props} ref={input} value={value} inputMode={useBuiltIn ? 'none' : props.inputMode} onChange={event => onValueChange(event.target.value)} onBlur={event => { props.onBlur?.(event); if (formatOnCommit && !host) { const next = formatOnCommit(event.currentTarget.value); if (next !== event.currentTarget.value) onValueChange(next); } }} onFocus={event => {
    props.onFocus?.(event); if (!skipFocus.current) open(event.currentTarget);
  }} onPointerDown={event => {
    props.onPointerDown?.(event);
    const touch = event.pointerType === 'touch' || event.pointerType === 'pen';
    if (!props.disabled && !props.readOnly && (useBuiltIn || touch)) { event.preventDefault(); open(event.currentTarget, touch); }
  }} />{host && createPortal(<KeyboardDialog initial={value} title={title} maxLength={props.maxLength}
    password={props.type === 'password'} numeric={props.inputMode === 'numeric' || props.inputMode === 'decimal'} capitalize={capitalize} hex={keyboardLayout === 'hex'}
    onCancel={close} onDone={next => { onValueChange(formatOnCommit ? formatOnCommit(next) : next); close(); }} />, host)}</>;
}
