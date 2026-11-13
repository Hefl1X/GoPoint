import { describe, expect, it } from 'vitest';
import { MOTION_MS, blendPoint, motionProgress } from './motion';

const A = { lat: 55.0, lon: 83.0 };
const B = { lat: 55.001, lon: 83.002 };

describe('плавный переход машины между двумя присланными положениями', () => {
  it('в начале машина там, где была, в конце там, где её прислали', () => {
    expect(blendPoint(A, B, 0)).toEqual(A);
    expect(blendPoint(A, B, 1)).toEqual(B);
  });

  it('посередине ровно между точками, за пределы отрезка не выходит', () => {
    const mid = blendPoint(A, B, 0.5);
    expect(mid.lat).toBeCloseTo(55.0005, 6);
    expect(mid.lon).toBeCloseTo(83.001, 6);
    const over = blendPoint(A, B, 3);
    expect(over).toEqual(B); // вперёд от присланного положения не угадываем
    expect(blendPoint(A, B, -1)).toEqual(A);
  });

  it('машина, которой раньше не было, появляется сразу на месте', () => {
    expect(blendPoint(null, B, 0.2)).toEqual(B);
  });

  it('слишком далёкий скачок (не движение, а смена данных) не растягиваем', () => {
    const far = { lat: 55.2, lon: 83.0 };
    expect(blendPoint(A, far, 0.3)).toEqual(far);
  });

  it('доля пути растёт со временем и не больше 1', () => {
    expect(motionProgress(0)).toBe(0);
    expect(motionProgress(MOTION_MS / 2)).toBeGreaterThan(0);
    expect(motionProgress(MOTION_MS / 2)).toBeLessThan(1);
    expect(motionProgress(MOTION_MS)).toBe(1);
    expect(motionProgress(MOTION_MS * 5)).toBe(1);
  });
});
