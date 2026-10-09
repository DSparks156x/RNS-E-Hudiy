export type TextEdit = { value: string; start: number; end: number };

const previous = (value: string, position: number) => {
  const end = Math.max(0, position - 1);
  return end > 0 && /[\uDC00-\uDFFF]/.test(value[end]) && /[\uD800-\uDBFF]/.test(value[end - 1]) ? end - 1 : end;
};
const next = (value: string, position: number) => {
  const end = Math.min(value.length, position + 1);
  return end < value.length && /[\uD800-\uDBFF]/.test(value[position]) && /[\uDC00-\uDFFF]/.test(value[end]) ? end + 1 : end;
};

export function insertText(edit: TextEdit, text: string, maxLength?: number): TextEdit {
  const available = maxLength === undefined ? Infinity : Math.max(0, maxLength - edit.value.length + edit.end - edit.start);
  let insertion = '';
  for (const character of text) {
    if (insertion.length + character.length > available) break;
    insertion += character;
  }
  const position = edit.start + insertion.length;
  return { value: edit.value.slice(0, edit.start) + insertion + edit.value.slice(edit.end), start: position, end: position };
}

export function backspace(edit: TextEdit): TextEdit {
  return insertText({ ...edit, start: edit.start === edit.end ? previous(edit.value, edit.start) : edit.start }, '');
}

export function moveCaret(edit: TextEdit, direction: -1 | 1): TextEdit {
  const position = edit.start !== edit.end ? direction < 0 ? edit.start : edit.end
    : direction < 0 ? previous(edit.value, edit.start) : next(edit.value, edit.end);
  return { ...edit, start: position, end: position };
}
