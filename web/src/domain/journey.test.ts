import { describe, expect, it } from 'vitest';
import {
  arrivalText,
  durationText,
  formatTime,
  hasNotLowFloor,
  headline,
  journeyKey,
  minutesUntil,
  segmentLabel,
  stopsText,
  timeline,
  transferSlackS,
  type Journey,
  type RideStep,
  type WalkStep,
} from './journey';

const stop = (name: string) => ({ id: name, name, point: { lat: 55, lon: 82.9 } });

const walk = (durationS: number): WalkStep => ({
  kind: 'walk',
  fromName: null,
  toName: null,
  distanceM: Math.round(durationS * 0.8),
  durationS,
  geometry: [],
  hasStairs: false,
});

const ride = (
  number: string,
  departAt: string,
  arriveAt: string,
  extra: Partial<RideStep> = {},
): RideStep => ({
  kind: 'ride',
  vehicleId: `v-${number}`,
  line: { id: `bus-${number}`, type: 'bus', number, title: '' },
  lowFloor: 'yes',
  boardStop: stop('Университет'),
  alightStop: stop('Площадь Маркса'),
  waitS: 0,
  stopsCount: 7,
  stopsAway: 2,
  toward: 'Вокзал',
  departAt,
  arriveAt,
  geometry: [],
  ...extra,
});

// 13:10 по Новосибирску = 06:10 UTC.
const JOURNEY: Journey = {
  steps: [
    walk(360), // до 06:16
    ride('8', '2026-11-04T06:20:00Z', '2026-11-04T06:32:00Z'),
    walk(120), // до 06:34
    ride('2', '2026-11-04T06:38:00Z', '2026-11-04T06:49:00Z', {
      line: { id: 'tram-2', type: 'tram', number: '2', title: '' },
      lowFloor: 'no',
    }),
    walk(240),
  ],
  departAt: '2026-11-04T06:10:00Z',
  arriveAt: '2026-11-04T06:53:00Z',
  durationS: 43 * 60,
  transfers: 1,
  lowFloorOnly: false,
  labels: [],
};

const NOW = Date.parse('2026-11-04T06:10:00Z');

describe('время', () => {
  it('по Новосибирску, 24 часа', () => {
    expect(formatTime('2026-11-04T06:10:00Z')).toBe('13:10');
    expect(formatTime('2026-11-04T13:05:00Z')).toBe('20:05');
  });

  it('через полночь', () => {
    expect(formatTime('2026-11-04T16:59:00Z')).toBe('23:59');
    expect(formatTime('2026-11-04T17:05:00Z')).toBe('00:05');
  });

  it('минуты до машины не уходят в минус', () => {
    expect(minutesUntil('2026-11-04T06:14:00Z', NOW)).toBe(4);
    expect(minutesUntil('2026-11-04T06:09:00Z', NOW)).toBe(0);
  });

  it('длительность словами', () => {
    expect(durationText(41 * 60)).toBe('41 минута');
    expect(durationText(62 * 60)).toBe('1 час 2 минуты');
    expect(durationText(120 * 60)).toBe('2 часа');
    expect(durationText(10)).toBe('1 минута');
  });
});

describe('подписи маршрута', () => {
  it('крупная строка: первая машина и минуты до неё', () => {
    expect(headline(JOURNEY, NOW)).toBe('Автобус 8 · 10 мин');
    expect(headline(JOURNEY, Date.parse('2026-11-04T06:20:30Z'))).toBe('Автобус 8 · подъезжает');
  });

  it('прибытие, время в пути, пересадки', () => {
    expect(arrivalText(JOURNEY)).toBe('Приедете в 13:53 · 43 минуты в пути · 1 пересадка');
    expect(arrivalText({ ...JOURNEY, transfers: 0 })).toContain('без пересадок');
  });

  it('пометка, если есть машина без подтверждённого низкого пола', () => {
    expect(hasNotLowFloor(JOURNEY)).toBe(true);
    const allYes = { ...JOURNEY, steps: JOURNEY.steps.slice(0, 3) };
    expect(hasNotLowFloor(allYes)).toBe(false);
  });

  it('остановки склоняются', () => {
    expect(stopsText(1)).toBe('1 остановка');
    expect(stopsText(3)).toBe('3 остановки');
    expect(stopsText(7)).toBe('7 остановок');
  });

  it('ключ маршрута по машинам', () => {
    expect(journeyKey(JOURNEY)).toBe('v-8>v-2');
  });
});

describe('шкала времени', () => {
  it('пешком, ожидание, поездка, пересадка с ожиданием', () => {
    const segments = timeline(JOURNEY);
    expect(segments.map((s) => s.kind)).toEqual([
      'walk',
      'wait',
      'ride',
      'walk',
      'wait',
      'ride',
      'walk',
    ]);
    expect(segments.map(segmentLabel)).toEqual([
      'пешком 6',
      'ожидание 4',
      'автобус 12',
      'пешком 2',
      'ожидание 4',
      'трамвай 11',
      'пешком 4',
    ]);
    const total = segments.reduce((sum, s) => sum + s.seconds, 0);
    expect(total).toBe(JOURNEY.durationS);
  });

  it('запас на пересадку только у второй поездки', () => {
    const [first, second] = JOURNEY.steps.filter((s): s is RideStep => s.kind === 'ride');
    expect(first && transferSlackS(JOURNEY, first)).toBeNull();
    expect(second && transferSlackS(JOURNEY, second)).toBe(4 * 60);
  });
});
