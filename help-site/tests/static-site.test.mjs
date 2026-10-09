import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
const root = new URL('../', import.meta.url);
const app = ['main.jsx', 'guide.jsx', 'ui.jsx', 'WheelExplainer.jsx', 'RnseFaceplate.jsx', 'HowToGuides.jsx', 'NavigationShowcase.jsx'].map(file => readFileSync(new URL(`src/${file}`, root), 'utf8')).join('\n');

test('every literal product illustration is shipped', () => {
  const references = [...app.matchAll(/(?:src=\"|src:\s*'|image:\s*')([^\"']+\.(?:png|jpg|gif))/g)].map(match => match[1].replace('./media/', ''));
  const samples = JSON.parse(readFileSync(new URL('src/navigation-examples.json', root), 'utf8'));
  references.push('nav-showcase-stock.gif', 'nav-showcase-bitmap.gif', ...samples.flatMap(sample => Object.values(sample.images)));
  assert.ok(references.length >= 6, 'Expected actual product render examples');
  for (const name of references) assert.ok(existsSync(new URL(`public/media/${name}`, root)), `Missing ${name}`);
  for (const name of references.filter(name => name.endsWith('.gif'))) {
    const still = { 'dataview-engine.gif': 'dataview-engine.jpg', 'dis-acceleration-run.gif': 'dis-acceleration.png' }[name] || name.replace('.gif', '.png');
    assert.ok(existsSync(new URL(`public/media/${still}`, root)), `Missing paused frame ${still}`);
  }
});

test('all guide topics and literal internal links resolve', () => {
  const guide = readFileSync(new URL('src/guide.jsx', root), 'utf8');
  const howTo = readFileSync(new URL('src/HowToGuides.jsx', root), 'utf8');
  const topics = [...(guide + howTo).matchAll(/\{ id: '([^']+)', group:/g)].map(match => match[1]);
  assert.equal(new Set(topics).size, topics.length, 'Topic IDs must be unique');
  assert.ok(topics.length >= 12, 'Cluster, data, controller and setup tasks need their own topics');
  const pageMap = guide.match(/export const Pages = \{([^}]+)\}/)[1] + howTo.match(/export const HowToPages = \{([^}]+)\}/)[1];
  assert.match(guide, /\.\.\.howToTopics/);
  assert.match(guide, /\.\.\.HowToPages/);
  for (const topic of topics) assert.match(pageMap, new RegExp(`\\b${topic}['"]?:`), `No page for ${topic}`);
  for (const [, destination] of app.matchAll(/href="#([^"{]+)"/g)) {
    assert.ok(destination === 'main-content' || topics.includes(destination), `Unresolved internal link #${destination}`);
  }
});

test('render assets have source provenance and synthetic-data disclosure', () => {
  for (const name of ['provenance.json', 'dataview-provenance.json', 'wheel-provenance.json', 'file-portal-provenance.json', 'navigation-showcase.json']) {
    const manifest = JSON.parse(readFileSync(new URL(`public/media/${name}`, root), 'utf8'));
    assert.match(manifest.data, /synthetic/i);
  }
});

test('static URLs and launcher work under repository subpaths', () => {
  const base = new URL('https://example.test/RNS-E-Hudiy/');
  assert.equal(new URL('./tools/config_editor.html', base).pathname, '/RNS-E-Hudiy/tools/config_editor.html');
  assert.match(app, /repo: 'DSparks156x\/RNS-E-Hudiy', branch: 'testing'/);
  assert.match(app, /load: '1'/);
  assert.match(readFileSync(new URL('vite.config.js', root), 'utf8'), /base: '\.\/'/);
  assert.doesNotMatch(app, /href=\"\/(?:tools|media|dis|dataview)/);
});

test('known feature limits are documented', () => {
  assert.match(app, /1000 m/);
  assert.match(app, /hard-disabled/);
  assert.match(app, /sent \/ unconfirmed/);
  assert.match(app, /hardware-bench acceptance/);
});
