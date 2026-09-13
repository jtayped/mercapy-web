import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import tseslint from 'typescript-eslint';

/**
 * shared typescript rules. consumers pass their source globs because each
 * workspace package owns its own tsconfig boundary.
 */
export function createTypeScriptConfig(files) {
  return [
    js.configs.recommended,
    ...tseslint.configs.strictTypeChecked.map((config) => ({ ...config, files })),
    ...tseslint.configs.stylisticTypeChecked.map((config) => ({ ...config, files })),
    {
      files,
      languageOptions: {
        parserOptions: {
          projectService: true,
          tsconfigRootDir: process.cwd(),
        },
      },
      rules: {
        '@typescript-eslint/ban-ts-comment': [
          'error',
          { 'ts-expect-error': 'allow-with-description', 'ts-ignore': true },
        ],
        '@typescript-eslint/no-explicit-any': 'error',
        '@typescript-eslint/no-floating-promises': 'error',
        '@typescript-eslint/switch-exhaustiveness-check': 'error',
      },
    },
    prettier,
  ];
}
