import { describe, expect, it } from 'vitest';
import {
  MUTED_COLOR,
  TYPE_COLOR,
  contrastRatio,
  filterLines,
  lineName,
  lowFloorLabel,
  onLineText,
  plural,
  towardStop,
  vehiclesOnLineText,
} from './transport';
import type { LineSummary } from './types';

describe('склонения', () => {
  it.each([
    [1, 'машина'],
    [2, 'машины'],
    [4, 'машины'],
    [5, 'машин'],
    [11, 'машин'],
    [12, 'машин'],
    [21, 'машина'],
    [22, 'машины'],
    [111, 'машин'],
    [0, 'машин'],
  ])('%i %s', (n, word) => {
    expect(plural(n, 'машина', 'машины', 'машин')).toBe(word);
  });

  it('строка «на линии сейчас»', () => {
    expect(onLineText(23, true)).toBe('На линии сейчас: 23 низкопольные машины');
    expect(onLineText(1, true)).toBe('На линии сейчас: 1 низкопольная машина');
    expect(onLineText(5, true)).toBe('На линии сейчас: 5 низкопольных машин');
    expect(onLineText(5, false)).toBe('На линии сейчас: 5 машин');
    expect(vehiclesOnLineText(3)).toBe('на линии: 3 машины');
  });
});

describe('пометки и названия', () => {
  it('три состояния низкого пола, unknown не выдаётся за yes', () => {
    expect(lowFloorLabel('yes')).toBe('низкий пол');
    expect(lowFloorLabel('no')).toBe('не низкий пол');
    expect(lowFloorLabel('unknown')).toBe('низкий пол не указан');
  });

  it('название маршрута', () => {
    expect(lineName('tram', '13')).toBe('Трамвай 13');
    expect(lineName('minibus', '45К')).toBe('Маршрутка 45К');
  });
});

describe('цвета', () => {
  it('белый номер на «таблетке» читается (контраст от 4.5:1)', () => {
    for (const color of [...Object.values(TYPE_COLOR), MUTED_COLOR]) {
      expect(contrastRatio('#ffffff', color)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('цвета текста из DESIGN.md на своих фонах', () => {
    const pairs: [string, string][] = [
      ['#17332e', '#f7fbfa'],
      ['#3d5650', '#f7fbfa'],
      ['#4a625c', '#f7fbfa'],
      ['#0f3d34', '#d7efe0'],
      ['#5c3f00', '#fff3d1'],
      ['#3d5650', '#d5dedb'],
      ['#ffffff', '#0f6b5c'],
      ['#0f6b5c', '#f7fbfa'],
    ];
    for (const [fg, bg] of pairs) expect(contrastRatio(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });
});

const lines: LineSummary[] = [
  { line: { id: 'bus-3', type: 'bus', number: '3', title: 'А — Б' }, vehiclesOnLine: 4 },
  { line: { id: 'bus-36', type: 'bus', number: '36', title: 'А — Б' }, vehiclesOnLine: 0 },
  { line: { id: 'tram-0013', type: 'tram', number: '13', title: 'А — Б' }, vehiclesOnLine: 2 },
  { line: { id: 'minibus-45', type: 'minibus', number: '45К', title: 'А' }, vehiclesOnLine: 1 },
];

describe('список «Транспорт сейчас»', () => {
  it('при включённой настройке только маршруты с машинами', () => {
    const ids = filterLines(lines, { type: 'all', query: '', lowFloorOnly: true }).map(
      (l) => l.line.id,
    );
    expect(ids).toEqual(['bus-3', 'tram-0013', 'minibus-45']);
  });

  it('при выключенной все, в том числе без машин', () => {
    expect(filterLines(lines, { type: 'all', query: '', lowFloorOnly: false })).toHaveLength(4);
  });

  it('фильтр по виду и поиск по началу номера, без учёта регистра', () => {
    expect(
      filterLines(lines, { type: 'bus', query: '3', lowFloorOnly: false }).map((l) => l.line.id),
    ).toEqual(['bus-3', 'bus-36']);
    expect(
      filterLines(lines, { type: 'all', query: '45к', lowFloorOnly: false }).map((l) => l.line.id),
    ).toEqual(['minibus-45']);
  });

  it('направление ведёт к последней остановке', () => {
    const stop = (name: string) => ({ id: name, name, point: { lat: 55, lon: 83 } });
    expect(
      towardStop({
        direction: 'A',
        stops: [stop('Вокзал'), stop('Северный')],
        path: [],
        vehicles: [],
      }),
    ).toBe('Северный');
  });
});
