import type { UseQueryResult } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { freshData } from './queries';

const query = (data: number[] | undefined, dataUpdatedAt: number) =>
  ({ data, dataUpdatedAt }) as UseQueryResult<number[]>;

describe('устаревшие данные не показываются', () => {
  it('свежие отдаются', () => {
    expect(freshData(query([1], 1_000), 300_000, 200_000)).toEqual([1]);
  });

  it('старше порога считаются отсутствием данных', () => {
    expect(freshData(query([1], 1_000), 300_000, 302_000)).toBeUndefined();
  });

  it('нет данных', () => {
    expect(freshData(query(undefined, 0), 300_000, 1)).toBeUndefined();
  });
});
