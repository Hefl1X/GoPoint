// Главный экран: карта с транспортом на линии, внизу панель или карточка машины.
import { Suspense, useMemo, useState } from 'react';
import { TYPE_COLOR, onLineText } from '../../domain/transport';
import type { LatLon } from '../../domain/types';
import { GeolocationError } from '../../ports/Geolocation';
import type { MapVehicle } from '../../ports/MapView';
import { LiveState, StatusBlock } from '../../shared/components';
import { useLine, useMeta, useOnline, useVehicles } from '../../shared/queries';
import { navigate, routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useServices } from '../../shared/services';
import { useSettings } from '../../shared/settings';
import { Sheet } from '../../shared/Sheet';
import { VehicleCard } from '../vehicle/VehicleCard';

const geoMessage: Record<GeolocationError['reason'], string> = {
  denied: ru.geo.denied,
  insecure: ru.geo.insecure,
  unavailable: ru.geo.unavailable,
  timeout: ru.geo.unavailable,
};

export function MapScreen({ vehicleId }: { vehicleId: string | null }) {
  const { MapView, geolocator } = useServices();
  const { lowFloorOnly } = useSettings();
  const online = useOnline();
  const meta = useMeta();
  const vehicles = useVehicles(lowFloorOnly);
  const selected = vehicles.data?.find((v) => v.id === vehicleId) ?? null;
  const line = useLine(selected?.lineId ?? null, lowFloorOnly);

  const [userLocation, setUserLocation] = useState<LatLon | null>(null);
  const [focus, setFocus] = useState<{ point: LatLon } | null>(null);
  const [geoState, setGeoState] = useState<'idle' | 'busy' | GeolocationError['reason']>('idle');

  const mapVehicles = useMemo<MapVehicle[]>(
    () =>
      (vehicles.data ?? []).map((v) => ({
        id: v.id,
        number: v.number,
        type: v.type,
        lowFloor: v.lowFloor,
        point: v.point,
        muted: selected !== null && v.lineId !== selected.lineId,
      })),
    [vehicles.data, selected],
  );

  const direction = selected
    ? line.data?.directions.find((d) => d.direction === selected.direction)
    : undefined;

  const locate = () => {
    setGeoState('busy');
    geolocator.locate().then(
      (point) => {
        setUserLocation(point);
        setFocus({ point });
        setGeoState('idle');
      },
      (error: unknown) => {
        setGeoState(error instanceof GeolocationError ? error.reason : 'unavailable');
      },
    );
  };

  return (
    <div className="map-screen">
      <h1 className="visually-hidden">{ru.appName}</h1>
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
            focus={focus}
            onVehicleSelect={(id) => {
              navigate({ name: 'map', vehicleId: id });
            }}
          />
        </Suspense>
      ) : (
        <div className="map-view map-view--loading" />
      )}

      <button
        type="button"
        className="map-locate"
        aria-label={ru.map.locate}
        onClick={locate}
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
    </div>
  );
}
