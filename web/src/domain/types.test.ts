import { describe, expect, it } from 'vitest';
import { isLowFloor } from './types';

describe('isLowFloor', () => {
  it('только yes считается низкопольной', () => {
    expect(isLowFloor('yes')).toBe(true);
    expect(isLowFloor('no')).toBe(false);
    expect(isLowFloor('unknown')).toBe(false);
  });
});
