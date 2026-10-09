import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { ignoreStatus } from '../scripts/netlify-ignore.mjs';

test('deployment builds first time and when commit history cannot be compared', () => {
  assert.equal(ignoreStatus({}), 1);
  assert.equal(ignoreStatus({ COMMIT_REF: 'a'.repeat(40) }), 1);
  assert.equal(ignoreStatus({ CACHED_COMMIT_REF: 'b'.repeat(40), COMMIT_REF: 'a'.repeat(40) }), 1);
});

test('Netlify ignores runtime-only commits and builds site changes, including deletions', () => {
  const temporaryRoot = resolve(tmpdir());
  const repository = mkdtempSync(join(temporaryRoot, 'rnse-deploy-test-'));
  function git(...args) {
    const result = spawnSync('git', ['-c', 'user.name=Site Test', '-c', 'user.email=site-test@example.invalid', '-c', 'commit.gpgsign=false', ...args], { cwd: repository, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  }
  function commit() { git('add', '.'); git('commit', '-qm', 'Fixture'); return git('rev-parse', 'HEAD'); }
  try {
    git('init', '-q');
    mkdirSync(join(repository, 'help-site'));
    writeFileSync(join(repository, 'help-site/index.html'), 'One');
    writeFileSync(join(repository, 'runtime.py'), 'One');
    const first = commit();
    writeFileSync(join(repository, 'runtime.py'), 'Two');
    const runtimeOnly = commit();
    assert.equal(ignoreStatus({ CACHED_COMMIT_REF: first, COMMIT_REF: runtimeOnly }, repository), 0);
    writeFileSync(join(repository, 'help-site/index.html'), 'Two');
    const siteChanged = commit();
    assert.equal(ignoreStatus({ CACHED_COMMIT_REF: runtimeOnly, COMMIT_REF: siteChanged }, repository), 1);
    rmSync(join(repository, 'help-site/index.html'));
    const siteDeleted = commit();
    assert.equal(ignoreStatus({ CACHED_COMMIT_REF: siteChanged, COMMIT_REF: siteDeleted }, repository), 1);
  } finally {
    assert.ok(resolve(repository).startsWith(temporaryRoot + sep));
    assert.ok(repository.includes('rnse-deploy-test-'));
    rmSync(repository, { recursive: true, force: true });
  }
});
