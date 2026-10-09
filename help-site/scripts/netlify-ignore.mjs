// Netlify's ignore command returns 0 to skip, 1 to build. It runs before npm ci.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

export function ignoreStatus(env = process.env, repository = fileURLToPath(new URL('../../', import.meta.url))) {
  const previous = env.CACHED_COMMIT_REF;
  const current = env.COMMIT_REF;
  // First deploys and shallow/missing history must build, never silently skip.
  if (!previous || !current || !/^[a-f0-9]{7,64}$/i.test(previous) || !/^[a-f0-9]{7,64}$/i.test(current)) return 1;
  const result = spawnSync('git', ['diff', '--quiet', '--no-ext-diff', previous, current, '--', 'help-site/'], { cwd: repository });
  return result.status === 0 ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const status = ignoreStatus();
  console.log(status === 0 ? 'No help-site changes; skip deployment.' : 'Build help site (changes or no previous deployment).');
  process.exitCode = status;
}
