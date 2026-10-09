import { mkdir, copyFile, readFile, writeFile } from 'node:fs/promises';
const snapshots = new URL('../tool-snapshots/', import.meta.url);
const output = new URL('../public/tools/', import.meta.url);
const names = ['config_editor.html', 'bitmap_tool.html', 'audscii_helper.html', 'theme_viewer.html'];
if (process.argv.includes('--refresh')) {
  await mkdir(snapshots, { recursive: true });
  for (const name of names) await copyFile(new URL(`../../tools/${name}`, import.meta.url), new URL(name, snapshots));
  const config = JSON.parse(await readFile(new URL('../../config.json', import.meta.url), 'utf8'));
  const defaults = new URL('../data/control-defaults.json', import.meta.url);
  await mkdir(new URL('../data/', import.meta.url), { recursive: true });
  await writeFile(defaults, JSON.stringify({ input_mappings: { mmi: config.input_mappings.mmi } }, null, 2) + '\n');
  console.log('Refreshed helper snapshots and faceplate defaults from the repository.');
}
await mkdir(output, { recursive: true });
for (const name of names) await copyFile(new URL(name, snapshots), new URL(name, output));
console.log('Copied versioned helper snapshots into the static site.');
