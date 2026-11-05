// Подписи для экрана остановки и карточки машины: через сколько минут и где машина.
// Способ расчёта времени не называется.
import { minutesUntil } from './journey';
import { plural } from './transport';
import type { StopArrival } from './types';

/**
 * Ближе этого прогноз показываем как есть («4 мин»), дальше со знаком «≈»:
 * чем дальше машина, тем больше она может задержаться в пути.
 */
export const EXACT_MINUTES_BELOW = 10;

/** «подъезжает», «4 мин», «≈ 12 мин». */
export function etaText(arriveAt: string, now: number): string {
  const minutes = minutesUntil(arriveAt, now);
  if (minutes === 0) return 'подъезжает';
  if (minutes < EXACT_MINUTES_BELOW) return `${String(minutes)} мин`;
  return `≈ ${String(minutes)} мин`;
}

/** Где машина сейчас относительно остановки: «следующая остановка», «в 3 остановках». */
export function stopsAwayText(stopsAway: number): string {
  if (stopsAway <= 0) return 'следующая остановка';
  return `в ${String(stopsAway)} ${plural(stopsAway, 'остановке', 'остановках', 'остановках')}`;
}

/** Машины, которые ещё не ушли, по времени прихода. */
export function upcoming(arrivals: readonly StopArrival[], now: number): StopArrival[] {
  return arrivals
    .filter((a) => Date.parse(a.arriveAt) >= now - 60_000)
    .sort((a, b) => Date.parse(a.arriveAt) - Date.parse(b.arriveAt));
}
