// Поиск адреса для точки А или Б (экран Suggestions): поле, «Моё местоположение»,
// «Выбрать на карте», подсказки. Пауза 300 мс, от 3 букв, старые запросы отменяются.
import { useEffect, useRef, useState } from 'react';
import { ENDPOINT_LETTER, KIND_LABEL, MIN_QUERY_LENGTH, normalizeQuery } from '../../domain/places';
import type { Endpoint, PlaceSuggestion, TripPoint } from '../../domain/types';
import { ApiError } from '../../ports/LiveApi';
import { BackButtonIcon, StatusBlock } from '../../shared/components';
import { usePlaceSearch } from '../../shared/placeQueries';
import { useOnline } from '../../shared/queries';
import { navigate } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useServices } from '../../shared/services';
import { useTrip } from '../../shared/trip';
import { EndpointBadge } from './TripCard';

export function SearchPanel({
  end,
  onUseLocation,
  locating,
}: {
  end: Endpoint;
  onUseLocation: (end: Endpoint) => void;
  locating: boolean;
}) {
  const { mapCanPick } = useServices();
  const { from, to, setPoint } = useTrip();
  const current = end === 'from' ? from : to;
  const [text, setText] = useState('');
  const search = usePlaceSearch(text);
  const online = useOnline();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
  }, []);

  const choose = (point: TripPoint) => {
    setPoint(end, point);
    navigate({ name: 'map', vehicleId: null }, { replace: true });
  };

  const close = () => {
    navigate({ name: 'map', vehicleId: null }, { replace: true });
  };

  const typed = normalizeQuery(text);
  const label = end === 'from' ? ru.search.fromLabel : ru.search.toLabel;

  return (
    <div className="search-panel" role="dialog" aria-modal="false" aria-label={label}>
      <div className="search-panel__bar">
        <button type="button" className="icon-button" aria-label={ru.back} onClick={close}>
          <BackButtonIcon />
        </button>
        <EndpointBadge end={end} />
        <label className="visually-hidden" htmlFor="place-search">
          {label}
        </label>
        <input
          ref={input}
          id="place-search"
          className="input search-panel__input"
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder={ru.search.placeholder}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') close();
          }}
        />
      </div>

      <div className="search-panel__actions">
        <button
          type="button"
          className="search-action"
          disabled={locating}
          onClick={() => {
            onUseLocation(end);
          }}
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
          >
            <circle cx="12" cy="12" r="6" />
            <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
          </svg>
          {locating ? ru.map.locating : ru.trip.myLocation}
        </button>
        {mapCanPick ? (
          <button
            type="button"
            className="search-action"
            onClick={() => {
              navigate({ name: 'pick', end }, { replace: true });
            }}
          >
            <svg
              viewBox="0 0 24 24"
              width="22"
              height="22"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
            >
              <path d="M12 21s-7-6.3-7-12a7 7 0 0 1 14 0c0 5.7-7 12-7 12Z" />
              <circle cx="12" cy="9" r="2.5" />
            </svg>
            {ru.trip.pickOnMap}
          </button>
        ) : null}
        {current ? (
          <button
            type="button"
            className="search-action"
            onClick={() => {
              setPoint(end, null);
              close();
            }}
          >
            {ru.search.clear} {ENDPOINT_LETTER[end]}
          </button>
        ) : null}
      </div>

      <div className="search-panel__results">
        <Results
          typed={typed}
          search={search}
          online={online}
          onChoose={(place) => {
            choose({ label: place.title, point: place.point });
          }}
        />
      </div>
      <p className="attribution search-panel__attribution">{ru.search.attribution}</p>
    </div>
  );
}

function Results({
  typed,
  search,
  online,
  onChoose,
}: {
  typed: string;
  search: ReturnType<typeof usePlaceSearch>;
  online: boolean;
  onChoose: (place: PlaceSuggestion) => void;
}) {
  const { query, pending } = search;
  if (typed.length === 0) return null;
  if (typed.length < MIN_QUERY_LENGTH) {
    return <p className="search-panel__hint">{ru.search.tooShort}</p>;
  }
  if (!online) {
    return <StatusBlock title={ru.errors.offlineTitle} text={ru.errors.offline} />;
  }
  if (pending) {
    return (
      <p className="search-panel__hint" role="status">
        {ru.search.searching}
      </p>
    );
  }
  if (query.isError) {
    const message = query.error instanceof ApiError ? query.error.message : ru.errors.generic;
    return (
      <div className="notice" role="alert">
        <p>{message}</p>
        <button
          type="button"
          className="button button--outline"
          onClick={() => {
            void query.refetch();
          }}
        >
          {ru.retry}
        </button>
      </div>
    );
  }
  const places = query.data ?? [];
  if (places.length === 0) {
    return (
      <div role="status">
        <StatusBlock title={ru.search.nothingTitle} text={ru.search.nothing} />
      </div>
    );
  }
  return (
    <>
      <p className="visually-hidden" role="status">
        {ru.search.found(places.length)}
      </p>
      <ul className="suggestions" aria-label={ru.search.resultsLabel}>
        {places.map((place) => (
          <li key={place.id}>
            <button
              type="button"
              className="suggestion"
              onClick={() => {
                onChoose(place);
              }}
            >
              <span className={`suggestion__kind suggestion__kind--${place.kind}`}>
                {KIND_LABEL[place.kind]}
              </span>
              <span className="suggestion__text">
                <span className="suggestion__title">{place.title}</span>
                {place.subtitle ? (
                  <span className="suggestion__subtitle">{place.subtitle}</span>
                ) : null}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
