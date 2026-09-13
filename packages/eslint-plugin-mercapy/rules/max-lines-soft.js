// the soft half of the file-length rule. eslint's own `max-lines` only has one
// severity, so it carries the hard limit (error at 1000) and this rule the warning
// at 500. scripts/check-file-length.mjs applies the same two numbers to every
// other language in the repo; keep the three in step.
const DEFAULT_MAX = 500;

export default {
  meta: {
    type: 'suggestion',
    docs: { description: 'warn when a file grows beyond the soft line limit' },
    schema: [
      {
        type: 'object',
        properties: { max: { type: 'integer', minimum: 1 } },
        additionalProperties: false,
      },
    ],
    messages: {
      tooLong: 'this file is {{count}} lines. the soft limit is {{max}}; it fails at 1000.',
    },
  },
  create(context) {
    const max = context.options[0]?.max ?? DEFAULT_MAX;
    return {
      'Program:exit'(node) {
        const count = context.sourceCode.lines.length;
        if (count > max) {
          context.report({ node, messageId: 'tooLong', data: { count, max } });
        }
      },
    };
  },
};
