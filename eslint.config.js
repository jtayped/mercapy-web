import boundaries from 'eslint-plugin-boundaries';
import importX from 'eslint-plugin-import-x';
import unicorn from 'eslint-plugin-unicorn';
import globals from 'globals';
import mercapy from './packages/eslint-plugin-mercapy/index.js';
import { createTypeScriptConfig } from './packages/config/eslint.base.js';

const typescriptFiles = [
  'apps/*/src/**/*.{ts,tsx}',
  'packages/*/src/**/*.{ts,tsx}',
  'packages/db/*.ts',
];

export default [
  {
    ignores: [
      '**/node_modules/**',
      '**/.next/**',
      '**/dist/**',
      '**/coverage/**',
      'packages/db/drizzle/**',
      'apps/collector/**',
    ],
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    languageOptions: { globals: globals.node },
  },
  ...createTypeScriptConfig(typescriptFiles),
  {
    files: typescriptFiles,
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { boundaries, 'import-x': importX, mercapy, unicorn },
    settings: {
      'boundaries/elements': [
        { type: 'web', pattern: 'apps/web/src/**' },
        { type: 'db', pattern: 'packages/db/**' },
        { type: 'contract', pattern: 'packages/contract/src/**' },
        { type: 'config', pattern: 'packages/config/**' },
      ],
      'import-x/resolver': { typescript: true },
    },
    rules: {
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          policies: [
            {
              from: { element: { type: 'web' } },
              allow: { to: { element: { types: { anyOf: ['web', 'db', 'contract', 'config'] } } } },
            },
            {
              from: { element: { type: 'db' } },
              allow: { to: { element: { types: { anyOf: ['db', 'contract', 'config'] } } } },
            },
            {
              from: { element: { type: 'contract' } },
              allow: { to: { element: { types: { anyOf: ['contract', 'config'] } } } },
            },
          ],
        },
      ],
      'import-x/no-cycle': 'error',
      // the pair behind `pnpm lint`: warn at 500, fail at 1000. see
      // scripts/check-file-length.mjs for the same numbers on python.
      'max-lines': ['error', { max: 1000 }],
      'mercapy/max-lines-soft': ['warn', { max: 500 }],
      'unicorn/no-array-reduce': 'off',
    },
  },
];
