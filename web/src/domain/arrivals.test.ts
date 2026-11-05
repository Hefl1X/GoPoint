import { describe, expect, it } from 'vitest';
import { etaText, stopsAwayText, upcoming } from './arrivals';
import type { StopArrival, Vehicle } from './types';

const NOW = Date.parse('2026-11-04T05:28:00Z');
const at = (minutes: number) => new Date(NOW + minutes * 60_000).toISOString();

const vehicle: Vehicle = {
  id: 'bus-8-1',
  lineId: 'bus-8',
  type: 'bus',
  number: '8',
  direction: 'A',
  point: { lat: 55, lon: 82.9 },
  lowFloor: 'yes',
};

describe('etaText', () => {
  it('близко: минуты как есть', () => {
    expect(etaText(at(4), NOW)).toBe('4 мин');
    expect(etaText(at(9), NOW)).toBe('9 мин');
  });
  it('далеко: со знаком «≈»', () => {
    expect(etaText(at(10), NOW)).toBe('≈ 10 мин');
    expect(etaText(at(12), NOW)).toBe('≈ 12 мин');
  });
  it('меньше полминуты: «подъезжает», прошедшее время не уходит в минус', () => {
    expect(etaText(at(0.2), NOW)).toBe('подъезжает');
    expect(etaText(at(-2), NOW)).toBe('подъезжает');
  });
  it('через полночь по Новосибирску считает минуты, а не часы', () => {
    const late = Date.parse('2026-11-04T16:58:00Z'); // 23:58 в Новосибирске
    expect(etaText(new Date(late + 5 * 60_000).toISOString(), late)).toBe('5 мин');
  });
});

describe('stopsAwayText', () => {
  it('склоняет по числу', () => {
    expect(stopsAwayText(0)).toBe('следующая остановка');
    expect(stopsAwayText(1)).toBe('в 1 остановке');
    expect(stopsAwayText(2)).toBe('в 2 остановках');
    expect(stopsAwayText(5)).toBe('в 5 остановках');
    expect(stopsAwayText(21)).toBe('в 21 остановке');
  });
});

describe('upcoming', () => {
  it('убирает ушедшие машины и сортирует по времени', () => {
    const items: StopArrival[] = [
      { vehicle, toward: null, stopsAway: 3, arriveAt: at(7) },
      { vehicle, toward: null, stopsAway: 1, arriveAt: at(2) },
      { vehicle, toward: null, stopsAway: 0, arriveAt: at(-5) },
    ];
    expect(upcoming(items, NOW).map((a) => a.stopsAway)).toEqual([1, 3]);
  });
});
