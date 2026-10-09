import { mkdir, copyFile } from 'node:fs/promises';
const output = new URL('../public/tools/', import.meta.url);
await mkdir(output, { recursive: true });
for (const name of ['config_editor.html', 'bitmap_tool.html', 'audscii_helper.html', 'theme_viewer.html']) {
  await copyFile(new URL(`../../tools/${name}`, import.meta.url), new URL(name, output));
}
console.log('Copied current standalone helpers into the static site.');
