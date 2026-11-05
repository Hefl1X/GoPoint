// Маршрут на линии: остановки по порядку и машины между ними.
import { Fragment, useState } from 'react';
import { lineName, towardStop, vehiclesOnLineText } from '../../domain/transport';
import type { Direction, LineDetails, LineVehicle } from '../../domain/types';
import {
  BackButton,
  LiveState,
  LowFloorBadge,
  OfflineNote,
  Pill,
  StatusBlock,
} from '../../shared/components';
import { useLine, useOnline } from '../../shared/queries';
import { routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useSettings } from '../../shared/settings';
import { useEffect, useRef } from 'react';

export function LiveRouteScreen({ lineId }: { lineId: string }) {
  const { lowFloorOnly } = useSettings();
  const online = useOnline();
  const line = useLine(lineId, lowFloorOnly);
  return (
    <main className="screen">
      <LiveState
        query={line.query}
        data={line.data}
        online={online}
        render={(details) => <LineView details={details} lowFloorOnly={lowFloorOnly} />}
      />
      {line.data === undefined ? (
        <div className="screen-head">
          <BackButton />
        </div>
      ) : null}
    </main>
  );
}

function LineView({ details, lowFloorOnly }: { details: LineDetails; lowFloorOnly: boolean }) {
  const [chosen, setChosen] = useState<Direction>('A');
  const direction = details.directions.find((d) => d.direction === chosen) ?? details.directions[0];
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  if (!direction) return <StatusBlock text={ru.errors.generic} />;
  const toward = towardStop(direction);
  const byStop = new Map<number | null, LineVehicle[]>();
  for (const item of direction.vehicles) {
    const list = byStop.get(item.nextStopOrder) ?? [];
    list.push(item);
    byStop.set(item.nextStopOrder, list);
  }
  const vehicleRows = (items: LineVehicle[] | undefined, text: string) =>
    items?.map(({ vehicle }) => (
      <li key={vehicle.id} className="route-vehicle">
        <a href={routeHref({ name: 'map', vehicleId: vehicle.id })} className="route-vehicle__link">
          <Pill type={vehicle.type} number={vehicle.number} lowFloor={vehicle.lowFloor} />
          <span>{text}</span>
          {lowFloorOnly ? null : <LowFloorBadge value={vehicle.lowFloor} />}
        </a>
      </li>
    ));

  return (
    <>
      <div className="screen-head">
        <BackButton />
        <Pill type={details.line.type} number={details.line.number} large />
        <div>
          <h1 ref={heading} tabIndex={-1}>
            {lineName(details.line.type, details.line.number)}
          </h1>
          {toward ? (
            <p className="screen-title__sub">
              {ru.vehicle.toward} {toward}
            </p>
          ) : null}
        </div>
      </div>
      {details.directions.length > 1 ? (
        <div className="segmented" role="group" aria-label={ru.line.directionLabel}>
          {details.directions.map((d) => (
            <button
              key={d.direction}
              type="button"
              className="segmented__item"
              aria-pressed={d.direction === direction.direction}
              onClick={() => {
                setChosen(d.direction);
              }}
            >
              {d.direction === 'A' ? ru.line.forward : ru.line.backward}
            </button>
          ))}
        </div>
      ) : null}
      {details.live ? (
        <p>
          <span className={`badge ${direction.vehicles.length > 0 ? 'badge--yes' : 'badge--grey'}`}>
            {direction.vehicles.length > 0
              ? vehiclesOnLineText(direction.vehicles.length)
              : ru.transport.notOnLine}
          </span>
        </p>
      ) : (
        <OfflineNote />
      )}
      <ol className="stops" aria-label={ru.line.stopsLabel}>
        {direction.stops.map((stop, order) => (
          <Fragment key={`${stop.id}-${String(order)}`}>
            {vehicleRows(byStop.get(order), `${ru.line.goesTo} «${stop.name}»`)}
            <li className="stop">
              <span className="stop__mark" aria-hidden="true" />
              <a
                className="stop__name stop__link"
                href={routeHref({ name: 'stop', stopId: stop.id })}
                aria-label={ru.stop.open(stop.name)}
              >
                {stop.name}
              </a>
            </li>
          </Fragment>
        ))}
        {vehicleRows(byStop.get(null), ru.line.atLastStop)}
      </ol>
    </>
  );
}
