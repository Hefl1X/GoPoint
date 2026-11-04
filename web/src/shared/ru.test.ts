import { describe, expect, it } from 'vitest';
import { ru } from './ru';

function allStrings(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (value && typeof value === 'object') return Object.values(value).flatMap(allStrings);
  return [];
}

describe('тексты интерфейса', () => {
  it('не упоминают способ отслеживания и время обновления', () => {
    const forbidden = [/gps/i, /обновлено/i, /по плану/i, /по расписанию/i, /спутник/i, /инвалид/i];
    for (const text of allStrings(ru)) {
      for (const word of forbidden) expect(text).not.toMatch(word);
    }
  });

  it('название приложения GoPoint', () => {
    expect(ru.appName).toBe('GoPoint');
  });
});
