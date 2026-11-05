// Карточка машины на карте: куда едет, низкий пол, следующая остановка с минутами,
// скорость, дальше по маршруту. Если минут нет (машина в стороне от линии),
// показывается только следующая остановка по линии.
import { etaText } from '../../domain/arrivals';
import { lineName, towardStop } from '../../domain/transport';
import type { LineDirection, Vehicle, VehicleDetails } from '../../domain/types';
import { LowFloorBadge, Pill, StatusBlock } from '../../shared/components';
import { routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useNow } from '../../shared/useNow';

// Сколько остановок показать в «Дальше по маршруту».
const FURTHER_STOPS = 3;

export function VehicleCard({
  vehicle,
  loading,
  direction,
  details,
  onClose,
}: {
  vehicle: Vehicle | null;
  loading: boolean;
  direction: LineDirection | undefined;
  details?: VehicleDetails | undefined;
  onClose: () => void;
}) {
  const now = useNow();
  const close = (
    <button type="button" className="icon-button" aria-label={ru.close} onClick={onClose}>
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
        <path
          d="M6 6l12 12M18 6L6 18"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );

  if (!vehicle) {
    return (
      <div className="vehicle-card">
        <div className="vehicle-card__head">
          <span />
          {close}
        </div>
        <StatusBlock text={loading ? ru.loading : ru.vehicle.gone} busy={loading} />
      </div>
    );
  }

  const timed = details?.vehicle.id === vehicle.id ? details.nextStops : [];
  const toward = details?.toward ?? (direction ? towardStop(direction) : null);
  const position = direction?.vehicles.find((item) => item.vehicle.id === vehicle.id);
  const nextStop =
    position && position.nextStopOrder !== null
      ? direction?.stops[position.nextStopOrder]
      : undefined;

  return (
    <article className="vehicle-card" aria-labelledby="vehicle-card-title">
      <div className="vehicle-card__head">
        <Pill type={vehicle.type} number={vehicle.number} lowFloor={vehicle.lowFloor} large />
        <div className="vehicle-card__titles">
          <h2 id="vehicle-card-title">{lineName(vehicle.type, vehicle.number)}</h2>
          <p className="muted">{toward ? `${ru.vehicle.toward} ${toward}` : null}</p>
          <LowFloorBadge value={vehicle.lowFloor} />
        </div>
        {close}
      </div>

      {timed[0] ? (
        <div className="next-stop">
          <p className="next-stop__label">{ru.vehicle.nextStop}</p>
          <p className="next-stop__name">
            {timed[0].stop.name} · {etaText(timed[0].arriveAt, now)}
          </p>
          {vehicle.speedKmh != null ? (
            <p className="next-stop__speed">
              {ru.vehicle.speed} {Math.round(vehicle.speedKmh)} {ru.vehicle.kmh}
            </p>
          ) : null}
        </div>
      ) : position ? (
        <div className="next-stop">
          <p className="next-stop__label">
            {nextStop ? ru.vehicle.nextStop : ru.vehicle.atTerminal}
          </p>
          <p className="next-stop__name">{nextStop ? nextStop.name : toward}</p>
          {vehicle.speedKmh != null ? (
            <p className="next-stop__speed">
              {ru.vehicle.speed} {Math.round(vehicle.speedKmh)} {ru.vehicle.kmh}
            </p>
          ) : null}
        </div>
      ) : null}

      {timed.length > 1 ? (
        <section aria-labelledby="vehicle-further">
          <h3 id="vehicle-further" className="next-stop__label">
            {ru.vehicle.further}
          </h3>
          <ul className="further">
            {timed.slice(1, 1 + FURTHER_STOPS).map((s) => (
              <li key={`${s.stop.id}-${s.arriveAt}`}>
                <span>{s.stop.name}</span>
                <span>{etaText(s.arriveAt, now)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <a
        className="button button--outline"
        href={routeHref({ name: 'line', lineId: vehicle.lineId })}
      >
        {ru.vehicle.allStops}
      </a>
      {timed.length > 0 ? <p className="route__note">{ru.vehicle.note}</p> : null}
    </article>
  );
}
