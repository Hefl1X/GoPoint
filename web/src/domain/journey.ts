// Маршрут «сейчас»: шаги, шкала времени, подписи. Чистые функции без React и сети.
// Время внутри UTC (ISO 8601), человеку показывается по Asia/Novosibirsk, 24 часа.
import { lineName, plural, typeName } from './transport';
import type { Accessibility, LatLon, Line, Stop } from './types';

export interface WalkStep {
  readonly kind: 'walk';
  /** Название места в начале и конце участка (остановка), если есть. */
  readonly fromName: string | null;
  readonly toName: string | null;
  readonly distanceM: number;
  readonly durationS: number;
  readonly geometry: readonly LatLon[];
  /** На пути есть лестница или эскалатор (обойти не удалось). */
  readonly hasStairs: boolean;
}

export interface RideStep {
  readonly kind: 'ride';
  readonly vehicleId: string;
  readonly line: Line;
  readonly lowFloor: Accessibility;
  readonly boardStop: Stop;
  readonly alightStop: Stop;
  readonly waitS: number;
  readonly stopsCount: number;
  readonly stopsAway: number;
  readonly toward: string | null;
  readonly departAt: string;
  readonly arriveAt: string;
  readonly geometry: readonly LatLon[];
}

export type JourneyStep = WalkStep | RideStep;

/** Чем вариант лучше других: быстрее всего, меньше пересадок, меньше пешком. */
export type VariantLabel = 'fastest' | 'fewest_transfers' | 'least_walking';

export interface Journey {
  readonly steps: readonly JourneyStep[];
  readonly departAt: string;
  readonly arriveAt: string;
  readonly durationS: number;
  readonly transfers: number;
  readonly lowFloorOnly: boolean;
  /** Пусто у запасного варианта на другой машине. */
  readonly labels: readonly VariantLabel[];
}

export interface RoutePlan {
  /** walk_better: машины есть, но пешком (walk) быстрее и меньше идти. */
  readonly status: 'ok' | 'no_transit' | 'walk_better';
  readonly journeys: readonly Journey[];
  /** Путь пешком от А до Б: отдельный выбор рядом с транспортом; null — не предлагать. */
  readonly walk: WalkStep | null;
}

export type CheckStatus = 'ok' | 'stopped' | 'late' | 'gone';

export interface RouteCheck {
  readonly status: CheckStatus;
  readonly stoppedForS: number | null;
  readonly current: Journey | null;
  readonly alternative: Journey | null;
}

export interface RoutePoints {
  readonly origin: LatLon;
  readonly destination: LatLon;
}

const TIME_FORMAT = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
  timeZone: 'Asia/Novosibirsk',
});

/** «08:40», «14:00»: всегда по Новосибирску, 24 часа. */
export function formatTime(iso: string): string {
  return TIME_FORMAT.format(new Date(iso));
}

/** Минуты с округлением вверх: лучше прийти раньше, чем опоздать. Не меньше 1. */
export function minutesOf(seconds: number): number {
  return Math.max(1, Math.ceil(seconds / 60));
}

/** Через сколько минут машина у остановки посадки (0, если уже подъезжает). */
export function minutesUntil(iso: string, now: number): number {
  return Math.max(0, Math.round((Date.parse(iso) - now) / 60_000));
}

export function rides(journey: Journey): RideStep[] {
  return journey.steps.filter((s): s is RideStep => s.kind === 'ride');
}

export function firstRide(journey: Journey): RideStep | null {
  return rides(journey)[0] ?? null;
}

/** «41 минута», «1 час 5 минут». */
export function durationText(seconds: number): string {
  const total = minutesOf(seconds);
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  const min = `${String(minutes)} ${plural(minutes, 'минута', 'минуты', 'минут')}`;
  if (hours === 0) return min;
  const h = `${String(hours)} ${plural(hours, 'час', 'часа', 'часов')}`;
  return minutes === 0 ? h : `${h} ${min}`;
}

/** «Автобус 8 · 4 мин» или «Автобус 8 · подъезжает». */
export function headline(journey: Journey, now: number): string {
  const ride = firstRide(journey);
  if (!ride) return '';
  const name = lineName(ride.line.type, ride.line.number);
  const minutes = minutesUntil(ride.departAt, now);
  return minutes === 0 ? `${name} · подъезжает` : `${name} · ${String(minutes)} мин`;
}

/** «Приедете в 13:51 · 41 минута в пути · 1 пересадка». */
export function arrivalText(journey: Journey): string {
  const parts = [`Приедете в ${formatTime(journey.arriveAt)}`];
  parts.push(`${durationText(journey.durationS)} в пути`);
  if (journey.transfers === 0) parts.push('без пересадок');
  else
    parts.push(
      `${String(journey.transfers)} ${plural(journey.transfers, 'пересадка', 'пересадки', 'пересадок')}`,
    );
  return parts.join(' · ');
}

/** В маршруте есть машины без подтверждённого низкого пола. */
export function hasNotLowFloor(journey: Journey): boolean {
  return rides(journey).some((r) => r.lowFloor !== 'yes');
}

export type SegmentKind = 'walk' | 'wait' | 'ride';

export interface TimelineSegment {
  readonly kind: SegmentKind;
  readonly seconds: number;
  /** Для поездки: вид транспорта и номер (цвет «таблетки»). */
  readonly ride?: RideStep;
}

/**
 * Шкала времени: пешком, ожидание (в том числе на пересадке), поездка.
 * Ожидание считается от прихода на остановку до подхода машины.
 */
export function timeline(journey: Journey): TimelineSegment[] {
  const segments: TimelineSegment[] = [];
  let clock = Date.parse(journey.departAt);
  for (const step of journey.steps) {
    if (step.kind === 'walk') {
      if (step.durationS > 0) segments.push({ kind: 'walk', seconds: step.durationS });
      clock += step.durationS * 1000;
      continue;
    }
    const depart = Date.parse(step.departAt);
    const wait = Math.round((depart - clock) / 1000);
    if (wait > 0) segments.push({ kind: 'wait', seconds: wait });
    const ride = Math.max(0, Math.round((Date.parse(step.arriveAt) - depart) / 1000));
    segments.push({ kind: 'ride', seconds: ride, ride: step });
    clock = Date.parse(step.arriveAt);
  }
  // Соседние куски одного вида объединяем: «пешком 10» вместо «пешком 4 + пешком 6».
  const merged: TimelineSegment[] = [];
  for (const s of segments) {
    const last = merged.at(-1);
    if (last && last.kind === s.kind && s.kind !== 'ride') {
      merged[merged.length - 1] = { ...last, seconds: last.seconds + s.seconds };
    } else merged.push(s);
  }
  return merged;
}

/** Подпись куска шкалы: «пешком 10», «ожидание 8», «автобус 12». */
export function segmentLabel(segment: TimelineSegment): string {
  const minutes = String(minutesOf(segment.seconds));
  if (segment.kind === 'walk') return `пешком ${minutes}`;
  if (segment.kind === 'wait') return `ожидание ${minutes}`;
  const ride = segment.ride;
  const name = ride ? typeName(ride.line.type).toLowerCase() : 'поездка';
  return `${name} ${minutes}`;
}

/** «7 остановок». */
export function stopsText(count: number): string {
  return `${String(count)} ${plural(count, 'остановка', 'остановки', 'остановок')}`;
}

/** Запас времени на пересадку перед поездкой (с), если это не первая поездка. */
export function transferSlackS(journey: Journey, ride: RideStep): number | null {
  const index = journey.steps.indexOf(ride);
  if (index < 0 || rides(journey)[0] === ride) return null;
  let clock: number | null = null;
  for (let i = index - 1; i >= 0; i -= 1) {
    const step = journey.steps[i];
    if (!step) break;
    if (step.kind === 'ride') {
      clock = Date.parse(step.arriveAt);
      // Пешие участки между поездками прибавляем.
      for (let j = i + 1; j < index; j += 1) {
        const w = journey.steps[j];
        if (w?.kind === 'walk') clock += w.durationS * 1000;
      }
      break;
    }
  }
  if (clock === null) return null;
  return Math.max(0, Math.round((Date.parse(ride.departAt) - clock) / 1000));
}

/** Путь пешком как маршрут из одного шага (для шкалы, шагов и карты). */
export function walkJourney(walk: WalkStep, departAt: string): Journey {
  return {
    steps: [walk],
    departAt,
    arriveAt: new Date(Date.parse(departAt) + walk.durationS * 1000).toISOString(),
    durationS: walk.durationS,
    transfers: 0,
    lowFloorOnly: false,
    labels: [],
  };
}

/** Сколько всего метров пешком в маршруте. */
export function walkingMetres(journey: Journey): number {
  return journey.steps.reduce((sum, s) => (s.kind === 'walk' ? sum + s.distanceM : sum), 0);
}

/** «≈ 640 м», «≈ 1,2 км»: округлено, чтобы не обещать лишней точности. */
export function metresText(metres: number): string {
  if (metres < 1000) return `≈ ${String(Math.round(metres / 10) * 10)} м`;
  return `≈ ${(Math.round(metres / 100) / 10).toLocaleString('ru-RU')} км`;
}

/** Строка карточки варианта: «41 минута · 1 пересадка · пешком ≈ 640 м». */
export function variantSummary(journey: Journey): string {
  const transfers =
    journey.transfers === 0
      ? 'без пересадок'
      : `${String(journey.transfers)} ${plural(journey.transfers, 'пересадка', 'пересадки', 'пересадок')}`;
  return `${durationText(journey.durationS)} · ${transfers} · пешком ${metresText(walkingMetres(journey))}`;
}

/** Набор машин маршрута: по нему понятно, тот же это маршрут или другой. */
export function journeyKey(journey: Journey): string {
  return rides(journey)
    .map((r) => r.vehicleId)
    .join('>');
}
