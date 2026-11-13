// Остановка: что подъезжает и через сколько минут, «Проложить маршрут отсюда».
// Набор машин зависит от настройки «Низкопольный транспорт».
import { useEffect, useRef } from 'react';
import { etaText, stopsAwayText, upcoming } from '../../domain/arrivals';
import { lineName } from '../../domain/transport';
import type { StopArrivals } from '../../domain/types';
import { BackButton, LiveState, LowFloorBadge, Pill, StatusBlock } from '../../shared/components';
import { useOnline, useStopArrivals } from '../../shared/queries';
import { navigate, routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useServices } from '../../shared/services';
import { useSettings } from '../../shared/settings';
import { useTrip } from '../../shared/trip';
import { useNow } from '../../shared/useNow';

export function LiveStopScreen({ stopId }: { stopId: string }) {
  const { lowFloorOnly } = useSettings();
  const online = useOnline();
  const arrivals = useStopArrivals(stopId, lowFloorOnly);
  return (
    <main className="screen">
      <LiveState
        query={arrivals.query}
        data={arrivals.data}
        online={online}
        render={(data) => <StopView data={data} lowFloorOnly={lowFloorOnly} />}
      />
      {arrivals.data === undefined ? (
        <div className="screen-head">
          <BackButton />
        </div>
      ) : null}
    </main>
  );
}

function StopView({ data, lowFloorOnly }: { data: StopArrivals; lowFloorOnly: boolean }) {
  const now = useNow();
  const { streetImagery } = useServices();
  const { to, setPoint } = useTrip();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const items = upcoming(data.arrivals, now);

  const routeFromHere = () => {
    setPoint('from', { label: data.stop.name, point: data.stop.point });
    // Если «Куда» уже выбрано, сразу строим маршрут; иначе просим выбрать.
    navigate(to ? { name: 'map', vehicleId: null } : { name: 'search', end: 'to' });
  };

  return (
    <>
      <div className="screen-head">
        <BackButton />
        <div>
          <h1 ref={heading} tabIndex={-1}>
            {data.stop.name}
          </h1>
          <p className="screen-title__sub">{ru.stop.kind}</p>
        </div>
      </div>
      <h2>{ru.stop.nearest}</h2>
      {items.length === 0 ? (
        <StatusBlock
          title={ru.live.noneTitle}
          text={lowFloorOnly ? ru.stop.noneLowFloor : ru.stop.noneAny}
        >
          {lowFloorOnly ? <a href={routeHref({ name: 'settings' })}>{ru.live.showAny}</a> : null}
        </StatusBlock>
      ) : (
        <ul className="card-list">
          {items.map((a) => (
            <li key={a.vehicle.id}>
              <a
                className="line-row arrival"
                href={routeHref({ name: 'map', vehicleId: a.vehicle.id })}
              >
                <Pill
                  type={a.vehicle.type}
                  number={a.vehicle.number}
                  lowFloor={a.vehicle.lowFloor}
                  large
                />
                <span className="line-row__text">
                  <span className="line-row__name">
                    {ru.stop.rideTitle(lineName(a.vehicle.type, a.vehicle.number), a.toward)}
                  </span>
                  <span className="muted">{stopsAwayText(a.stopsAway)}</span>
                  {lowFloorOnly ? null : <LowFloorBadge value={a.vehicle.lowFloor} />}
                </span>
                <span
                  className={`arrival__time${Date.parse(a.arriveAt) - now < 30_000 ? ' arrival__time--now' : ''}`}
                >
                  {etaText(a.arriveAt, now)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="button button--primary" onClick={routeFromHere}>
        {ru.stop.routeFrom}
      </button>
      <a
        className="button button--outline"
        href={streetImagery.panoramaUrl(data.stop.point)}
        target="_blank"
        rel="noopener noreferrer"
      >
        {ru.stop.panorama}
      </a>
      <p className="route__note">{ru.stop.panoramaNote}</p>
      <p className="route__note">{ru.stop.note}</p>
    </>
  );
}
