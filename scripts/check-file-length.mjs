// file-length gate for every source language in the repo: a warning past 500
// lines, a failure past 1000. eslint enforces the same pair on typescript so
// editors show it inline; this script is what ci and the hooks run.
//
//   node scripts/check-file-length.mjs            # every tracked source file
//   node scripts/check-file-length.mjs a.py b.ts  # only these
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const WARN_AT = 500;
const FAIL_AT = 1000;
const SOURCE = /\.(ts|tsx|js|mjs|cjs|py|css|sql)$/;
const GENERATED = [/^packages\/db\/drizzle\//, /^packages\/contract\/schema\//, /\.lock$/];

function trackedFiles() {
  const output = execFileSync('git', [
    'ls-files',
    '-z',
    '--cached',
    '--others',
    '--exclude-standard',
  ]);
  return output.toString().split('\0').filter(Boolean);
}

const requested = process.argv.slice(2);
const files = (requested.length > 0 ? requested : trackedFiles()).filter(
  (file) => SOURCE.test(file) && !GENERATED.some((pattern) => pattern.test(file)),
);

let failed = false;
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  const lines = text.length === 0 ? 0 : text.split('\n').length - (text.endsWith('\n') ? 1 : 0);
  if (lines > FAIL_AT) {
    failed = true;
    console.error(`error: ${file} is ${lines} lines, over the ${FAIL_AT} limit`);
  } else if (lines > WARN_AT) {
    console.warn(`warning: ${file} is ${lines} lines, over the ${WARN_AT} soft limit`);
  }
}

process.exit(failed ? 1 : 0);
