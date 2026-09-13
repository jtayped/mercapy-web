import { describe, expect, it } from 'vitest';
import { eventValue, summaryData } from './json.ts';

describe('summaryData', () => {
  it('rejects keys the collector does not write', () => {
    const result = summaryData.safeParse({ id: '1', name: 'x', share_url: 'https://…' });
    expect(result.success).toBe(false);
  });
});

describe('eventValue', () => {
  it('accepts a price pair and nothing else', () => {
    expect(eventValue.parse({ tracked_price: '1.20', tracked_price_basis: 'unit' })).toEqual({
      tracked_price: '1.20',
      tracked_price_basis: 'unit',
    });
    expect(eventValue.safeParse({ price: '1.20' }).success).toBe(false);
  });
});
