const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { insertText, backspace, moveCaret } = require('../src/components/touchKeyboard/editing.ts');
const edit = (value, start = value.length, end = start) => ({ value, start, end });

test('typing replaces a selected name and leaves the cursor after the inserted text', () => {
  assert.deepEqual(insertText(edit('Daily', 0, 5), 'Track'), edit('Track'));
  assert.deepEqual(insertText(edit('Coolnt', 4), 'a'), edit('Coolant', 5));
});
test('page and profile limits allow selected replacements at maximum length', () => {
  assert.deepEqual(insertText(edit('123456789012'), 'x', 12), edit('123456789012'));
  assert.deepEqual(insertText(edit('123456789012', 9, 12), 'ABCDEF', 12), edit('123456789ABC'));
  assert.deepEqual(insertText(edit('12345678901'), '😀', 12), edit('12345678901'));
});
test('backspace deletes selections or a whole previous character without wrapping at the beginning', () => {
  assert.deepEqual(backspace(edit('Cold start', 5, 10)), edit('Cold ', 5));
  assert.deepEqual(backspace(edit('x😀')), edit('x'));
  assert.deepEqual(backspace(edit('Daily', 0)), edit('Daily', 0));
});
test('cursor controls collapse selections and respect string boundaries and surrogate pairs', () => {
  assert.deepEqual(moveCaret(edit('Daily', 1, 4), -1), edit('Daily', 1));
  assert.deepEqual(moveCaret(edit('Daily', 1, 4), 1), edit('Daily', 4));
  assert.deepEqual(moveCaret(edit('x😀', 1), 1), edit('x😀', 3));
  assert.deepEqual(moveCaret(edit('x😀', 3), -1), edit('x😀', 1));
  assert.deepEqual(moveCaret(edit('Daily', 0), -1), edit('Daily', 0));
  assert.deepEqual(moveCaret(edit('Daily'), 1), edit('Daily'));
});
