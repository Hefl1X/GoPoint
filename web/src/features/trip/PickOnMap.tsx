// Выбор точки на карте (экран PickOnMap): булавка в центре, карта двигается под ней,
// внизу адрес точки и кнопка «Выбрать эту точку».
import { ENDPOINT_LETTER } from '../../domain/places';
import type { Endpoint, LatLon } from '../../domain/types';
import { ApiError } from '../../ports/LiveApi';
import { useReversePlace } from '../../shared/placeQueries';
import { navigate } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useTrip } from '../../shared/trip';

/** Булавка ровно в центре карты (рисуется поверх, нажатия проходят на карту). */
export function CenterPin({ end }: { end: Endpoint }) {
  return (
    <div className="center-pin" aria-hidden="true">
      <div className={`trip-marker trip-marker--${end}`}>
        <span className="trip-marker__letter">{ENDPOINT_LETTER[end]}</span>
      </div>
    </div>
  );
}

export function PickHint({ end }: { end: Endpoint }) {
  const letter = ENDPOINT_LETTER[end];
  return (
    <div className="pick-hint">
      <div>
        <p className="pick-hint__title">{ru.pick.title(letter)}</p>
        <p className="pick-hint__text">{ru.pick.hint}</p>
      </div>
      <button
        type="button"
        className="icon-button"
        aria-label={ru.pick.cancel}
        onClick={() => {
          navigate({ name: 'map', vehicleId: null }, { replace: true });
        }}
      >
        <svg
          viewBox="0 0 24 24"
          width="22"
          height="22"
          aria-hidden="true"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
        >
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  );
}

export function PickPanel({ end, center }: { end: Endpoint; center: LatLon | null }) {
  const { setPoint } = useTrip();
  const reverse = useReversePlace(center);
  const letter = ENDPOINT_LETTER[end];
  const outside = reverse.error instanceof ApiError && reverse.error.code === 'OUTSIDE_CITY';

  let address: string;
  if (center === null || reverse.isFetching) address = ru.pick.lookingUp;
  else if (outside && reverse.error instanceof ApiError) address = reverse.error.message;
  else if (reverse.isError) address = ru.pick.lookupFailed;
  else address = reverse.data?.title ?? ru.trip.pointOnMap;

  return (
    <div className="pick-panel">
      <p className="pick-panel__caption">{ru.pick.addressOf(letter)}</p>
      <p className="pick-panel__address" aria-live="polite">
        {address}
      </p>
      <button
        type="button"
        className="button button--primary"
        disabled={center === null || outside}
        onClick={() => {
          if (!center) return;
          const label = reverse.isFetching ? ru.trip.pointOnMap : reverse.data?.title;
          setPoint(end, { label: label ?? ru.trip.pointOnMap, point: center });
          navigate({ name: 'map', vehicleId: null }, { replace: true });
        }}
      >
        {ru.pick.confirm}
      </button>
    </div>
  );
}
