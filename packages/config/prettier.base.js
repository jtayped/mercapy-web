import * as tailwind from 'prettier-plugin-tailwindcss';

/** @type {import('prettier').Config} */
const config = {
  plugins: [tailwind],
  printWidth: 100,
  singleQuote: true,
  trailingComma: 'all',
};

export default config;
