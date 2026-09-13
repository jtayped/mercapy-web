import maxLinesSoft from './rules/max-lines-soft.js';

const plugin = {
  meta: { name: 'eslint-plugin-mercapy', version: '0.0.0' },
  rules: {
    'max-lines-soft': maxLinesSoft,
  },
};

export default plugin;
