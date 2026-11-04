// Главный экран: карта с транспортом на линии, вверху поля «Откуда/Куда»,
// внизу панель или карточка машины. Здесь же поиск адреса и выбор точки на карте:
// карта при этом не пересоздаётся.
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { journeyKey, rides, type Journey } from '../../domain/journey';
import { nextEndpoint } from '../../domain/places';
import { TYPE_COLOR, onLineText } from '../../domain/transport';
import type { Endpoint, LatLon, TripPoint } from '../../domain/types';
import { GeolocationError } from '../../ports/Geolocation';
import type { MapJourneyLine, MapTripPoint, MapVehicle, MapViewProps } from '../../ports/MapView';
import { LiveState, StatusBlock } from '../../shared/components';
import { useLine, useMeta, useOnline, useVehicles } from '../../shared/queries';
import { navigate, routeHref, type Route } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useServices } from '../../shared/services';
import { useSettings } from '../../shared/settings';
import { Sheet } from '../../shared/Sheet';
import { useTrip } from '../../shared/trip';
import { CenterPin, PickHint, PickPanel } from '../trip/PickOnMap';
import { SearchPanel } from '../trip/SearchPanel';
import { RoutePanel } from '../route/RoutePanel';
import { TripCard } from '../trip/TripCard';
import { VehicleCard } from '../vehicle/VehicleCard';

type MapRoute = Extract<Route, { name: 'map' | 'search' | 'pick' }>;

/** Сдвинуть карту к точке, которую только что выбрали (а не при каждом рендере). */
function useFocusOnNewPoint(point: TripPoint | null, focus: (p: LatLon) => void): void {
  const previous = useRef(point);
  useEffect(() => {
    if (point && point !== previous.current) focus(point.point);
    previous.current = point;
  }, [point, focus]);
}

const geoMessage: Record<GeolocationError['reason'], string> = {
  denied: ru.geo.denied,
  insecure: ru.geo.insecure,
  unavailable: ru.geo.unavailable,
  timeout: ru.geo.unavailable,
};

export function MapScreen({ route }: { route: MapRoute }) {
  const vehicleId = route.name === 'map' ? route.vehicleId : null;
  const pickingEnd: Endpoint | null = route.name === 'pick' ? route.end : null;
  const { MapView, geolocator, mapCanPick } = useServices();
  const trip = useTrip();
  const { lowFloorOnly } = useSettings();
  const online = useOnline();
  const meta = useMeta();
  const vehicles = useVehicles(lowFloorOnly);
  const selected = vehicles.data?.find((v) => v.id === vehicleId) ?? null;
  const line = useLine(selected?.lineId ?? null, lowFloorOnly);

  const [userLocation, setUserLocation] = useState<LatLon | null>(null);
  const [focus, setFocus] = useState<MapViewProps['focus']>(null);
  const [geoState, setGeoState] = useState<'idle' | 'busy' | GeolocationError['reason']>('idle');
  const [center, setCenter] = useState<LatLon | null>(null);
  const [journey, setJourney] = useState<Journey | null>(null);
  const [fitPoints, setFitPoints] = useState<LatLon[] | null>(null);
  const shownKey = useRef<string | null>(null);
  const onJourney = useCallback((j: Journey | null) => {
    setJourney(j);
    // Карта показывает маршрут целиком один раз, когда он появился или сменился
    // (а не каждые 30 с, когда уточняется время).
    const key = j ? journeyKey(j) : null;
    if (key !== shownKey.current) {
      shownKey.current = key;
      if (j) setFitPoints(j.steps.flatMap((s) => [...s.geometry]));
    }
  }, []);

  const routePoints = useMemo(
    () => (trip.from && trip.to ? { origin: trip.from.point, destination: trip.to.point } : null),
    [trip.from, trip.to],
  );
  const journeyVehicles = useMemo(
    () => new Set(journey ? rides(journey).map((r) => r.vehicleId) : []),
    [journey],
  );
  const journeyLines = useMemo<MapJourneyLine[]>(
    () =>
      (journey?.steps ?? []).map((step) =>
        step.kind === 'walk'
          ? { kind: 'walk', points: step.geometry, color: '' }
          : { kind: 'ride', points: step.geometry, color: TYPE_COLOR[step.line.type] },
      ),
    [journey],
  );

  const focusOn = useMemo(
    () =>
      (point: LatLon, exact = false) => {
        setFocus({ point, exact });
      },
    [],
  );
  useFocusOnNewPoint(trip.from, focusOn);
  useFocusOnNewPoint(trip.to, focusOn);

  // Начали выбирать точку: если она уже стоит, булавка встаёт на неё.
  // Точки читаем через ref: эффект нужен только при входе в режим выбора.
  const tripRef = useRef(trip);
  useEffect(() => {
    tripRef.current = trip;
  });
  useEffect(() => {
    if (pickingEnd === null) return;
    const existing = pickingEnd === 'from' ? tripRef.current.from : tripRef.current.to;
    if (existing) focusOn(existing.point, true);
  }, [pickingEnd, focusOn]);

  const tripPoints = useMemo<MapTripPoint[]>(() => {
    const list: MapTripPoint[] = [];
    // Выбираемую точку показывает булавка в центре, старый значок прячем.
    if (trip.from && pickingEnd !== 'from')
      list.push({ end: 'from', point: trip.from.point, label: trip.from.label });
    if (trip.to && pickingEnd !== 'to')
      list.push({ end: 'to', point: trip.to.point, label: trip.to.label });
    return list;
  }, [trip.from, trip.to, pickingEnd]);

  const mapVehicles = useMemo<MapVehicle[]>(
    () =>
      (vehicles.data ?? []).map((v) => ({
        id: v.id,
        number: v.number,
        type: v.type,
        lowFloor: v.lowFloor,
        point: v.point,
        muted:
          selected !== null
            ? v.lineId !== selected.lineId
            : journeyVehicles.size > 0 && !journeyVehicles.has(v.id),
      })),
    [vehicles.data, selected, journeyVehicles],
  );

  const direction = selected
    ? line.data?.directions.find((d) => d.direction === selected.direction)
    : undefined;

  const locate = (end?: Endpoint) => {
    setGeoState('busy');
    geolocator.locate().then(
      (point) => {
        setUserLocation(point);
        setFocus({ point });
        setGeoState('idle');
        if (end) {
          trip.setPoint(end, { label: ru.trip.myLocation, point });
          navigate({ name: 'map', vehicleId: null }, { replace: true });
        }
      },
      (error: unknown) => {
        setGeoState(error instanceof GeolocationError ? error.reason : 'unavailable');
        // Сообщение об ошибке видно на главном экране.
        if (end) navigate({ name: 'map', vehicleId: null }, { replace: true });
      },
    );
  };

  return (
    <div className="map-screen">
      <h1 className="visually-hidden">{ru.appName}</h1>
      {/* Пока открыт поиск адреса, карта под ним недоступна для нажатий и читалки. */}
      <div className="map-layer" inert={route.name === 'search'}>
        {meta.data ? (
          <Suspense fallback={<div className="map-view map-view--loading" />}>
            <MapView
              label={ru.map.label}
              bounds={meta.data.cityBounds}
              vehicles={mapVehicles}
              selectedVehicleId={selected?.id ?? null}
              routeLine={direction?.path ?? null}
              routeColor={selected ? TYPE_COLOR[selected.type] : TYPE_COLOR.bus}
              userLocation={userLocation}
              journeyLines={vehicleId ? [] : journeyLines}
              fitPoints={fitPoints}
              focus={focus}
              tripPoints={tripPoints}
              picking={pickingEnd !== null}
              onCenterChange={setCenter}
              onVehicleSelect={(id) => {
                navigate({ name: 'map', vehicleId: id });
              }}
            />
          </Suspense>
        ) : (
          <div className="map-view map-view--loading" />
        )}
      </div>

      {pickingEnd ? (
        <>
          <CenterPin end={pickingEnd} />
          <PickHint end={pickingEnd} />
          <PickPanel end={pickingEnd} center={center} />
        </>
      ) : route.name === 'map' ? (
        <>
          <TripCard />
          <button
            type="button"
            className="map-locate"
            aria-label={ru.map.locate}
            onClick={() => {
              locate();
            }}
            disabled={geoState === 'busy'}
          >
            <svg
              viewBox="0 0 24 24"
              width="24"
              height="24"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <circle cx="12" cy="12" r="6" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
            </svg>
          </button>
          {/* Новый ключ при выборе машины: панель снова раскрывается. */}
          <Sheet key={vehicleId ?? 'start'} label={vehicleId ? undefined : ru.tagline}>
            {vehicleId ? (
              <VehicleCard
                vehicle={selected}
                loading={vehicles.data === undefined}
                direction={direction}
                onClose={() => {
                  navigate({ name: 'map', vehicleId: null });
                }}
              />
            ) : (
              <>
                {routePoints ? (
                  <RoutePanel
                    points={routePoints}
                    lowFloorOnly={lowFloorOnly}
                    onJourney={onJourney}
                  />
                ) : (
                  <div className="start-intro">
                    <h2 className="start-intro__title">{ru.trip.whereTo}</h2>
                    <p>{ru.trip.startHint}</p>
                    {mapCanPick ? (
                      <button
                        type="button"
                        className="button button--outline"
                        onClick={() => {
                          navigate({ name: 'pick', end: nextEndpoint(trip.from, trip.to) });
                        }}
                      >
                        {ru.trip.pickOnMap}
                      </button>
                    ) : null}
                  </div>
                )}
                <LiveState
                  query={vehicles.query}
                  data={vehicles.data}
                  online={online}
                  render={(list) =>
                    list.length > 0 ? (
                      <p className="on-line">
                        <svg
                          viewBox="0 0 24 24"
                          width="20"
                          height="20"
                          aria-hidden="true"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                        >
                          <rect x="5" y="3" width="14" height="15" rx="3" />
                          <path d="M5 11h14M8 18v3M16 18v3" />
                        </svg>
                        {onLineText(list.length, lowFloorOnly)}
                      </p>
                    ) : (
                      <StatusBlock
                        title={ru.live.noneTitle}
                        text={lowFloorOnly ? ru.live.noneLowFloor : ru.live.noneAny}
                      >
                        {lowFloorOnly ? (
                          <a href={routeHref({ name: 'settings' })}>{ru.live.showAny}</a>
                        ) : null}
                      </StatusBlock>
                    )
                  }
                />
                {geoState === 'busy' ? <p role="status">{ru.map.locating}</p> : null}
                {geoState !== 'idle' && geoState !== 'busy' ? (
                  <div className="notice" role="alert">
                    {geoState === 'denied' ? (
                      <p className="notice__title">{ru.geo.deniedTitle}</p>
                    ) : null}
                    <p>{geoMessage[geoState]}</p>
                  </div>
                ) : null}
                <a className="link" href={routeHref({ name: 'about' })}>
                  {ru.map.about}
                </a>
              </>
            )}
          </Sheet>
        </>
      ) : null}

      {route.name === 'search' ? (
        <SearchPanel
          key={route.end}
          end={route.end}
          locating={geoState === 'busy'}
          onUseLocation={(end) => {
            locate(end);
          }}
        />
      ) : null}
    </div>
  );
}
