// Карточка вверху карты: поля «Откуда» (А) и «Куда» (Б) и кнопка «поменять местами».
// Поля открывают поиск адреса (экран подсказок).
import { ENDPOINT_LETTER } from '../../domain/places';
import type { Endpoint, TripPoint } from '../../domain/types';
import { navigate } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useTrip } from '../../shared/trip';

export function EndpointBadge({ end }: { end: Endpoint }) {
  return (
    <span className={`endpoint-badge endpoint-badge--${end}`} aria-hidden="true">
      {ENDPOINT_LETTER[end]}
    </span>
  );
}

function Field({ end, value }: { end: Endpoint; value: TripPoint | null }) {
  const name = end === 'from' ? ru.trip.from : ru.trip.to;
  return (
    <button
      type="button"
      className="trip-card__field"
      onClick={() => {
        navigate({ name: 'search', end });
      }}
    >
      <EndpointBadge end={end} />
      {value ? (
        <span className="trip-card__value">
          {/* Читалка слышит и что это за поле, и что в нём выбрано. */}
          <span className="visually-hidden">{name}:</span> {value.label}
        </span>
      ) : (
        <span className="trip-card__placeholder">{name}</span>
      )}
    </button>
  );
}

export function TripCard() {
  const { from, to, swap } = useTrip();
  return (
    <section className="trip-card" aria-label={ru.trip.cardLabel}>
      <div className="trip-card__fields">
        <Field end="from" value={from} />
        <Field end="to" value={to} />
      </div>
      <button
        type="button"
        className="trip-card__swap"
        aria-label={ru.trip.swap}
        onClick={swap}
        disabled={from === null && to === null}
      >
        <svg
          viewBox="0 0 24 24"
          width="22"
          height="22"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M8 4v16M4 8l4-4 4 4M16 20V4M12 16l4 4 4-4" />
        </svg>
      </button>
    </section>
  );
}
