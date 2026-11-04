// Панель маршрута «сейчас» (DESIGN.md: Friendly, FriendlyOff, RouteDetails, FriendlyLoading,
// FriendlyNoRoute, FriendlyOffline, FriendlyRerouted, OutsideCity). Маршрут не заменяется
// молча: при пересчёте решает человек.
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type CSSProperties } from 'react';
import {
  arrivalText,
  firstRide,
  formatTime,
  hasNotLowFloor,
  headline,
  journeyKey,
  minutesOf,
  minutesUntil,
  segmentLabel,
  stopsText,
  timeline,
  transferSlackS,
  type Journey,
  type JourneyStep,
  type RideStep,
  type RoutePoints,
  type WalkStep,
} from '../../domain/journey';
import { lineName, TYPE_COLOR, typeName } from '../../domain/transport';
import { ApiError } from '../../ports/LiveApi';
import { LowFloorBadge, Pill, StatusBlock } from '../../shared/components';
import { useOnline, useRouteCheck, useRoutePlan } from '../../shared/queries';
import { navigate, routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useNow } from '../../shared/useNow';

const chooseOtherPoints = () => {
  navigate({ name: 'search', end: 'to' });
};

export function RoutePanel({
  points,
  lowFloorOnly,
  onJourney,
}: {
  points: RoutePoints;
  lowFloorOnly: boolean;
  /** Какой маршрут сейчас показан (для карты); null, если никакого. */
  onJourney: (journey: Journey | null) => void;
}) {
  const plan = useRoutePlan(points, lowFloorOnly);
  const online = useOnline();
  const client = useQueryClient();
  const [cancelled, setCancelled] = useState(false);

  const retry = () => {
    setCancelled(false);
    void plan.refetch();
  };

  if (cancelled) {
    return (
      <StatusBlock title={ru.route.cancelled}>
        <button type="button" className="button button--outline" onClick={retry}>
          {ru.route.searchAgain}
        </button>
      </StatusBlock>
    );
  }

  if (plan.isFetching && !plan.data) {
    return (
      <StatusBlock
        title={ru.route.searching}
        text={lowFloorOnly ? ru.route.searchingLowFloor : ru.route.searchingAny}
        busy
      >
        <div className="route-skeleton" aria-hidden="true" />
        <button
          type="button"
          className="button button--outline"
          onClick={() => {
            void client.cancelQueries({ queryKey: ['route'] });
            setCancelled(true);
          }}
        >
          {ru.route.cancel}
        </button>
      </StatusBlock>
    );
  }

  if (plan.isError) {
    const error = plan.error instanceof ApiError ? plan.error : null;
    if (!online || error?.code === 'NETWORK' || error?.code === 'TIMEOUT') {
      return (
        <StatusBlock
          title={error?.code === 'TIMEOUT' ? ru.route.failedTitle : ru.errors.offlineTitle}
          text={error?.code === 'TIMEOUT' ? error.message : ru.route.offline}
          onRetry={retry}
        />
      );
    }
    if (error?.code === 'OUTSIDE_CITY') {
      return (
        <StatusBlock title={ru.route.outsideTitle} text={ru.route.outside}>
          <button type="button" className="button button--outline" onClick={chooseOtherPoints}>
            {ru.route.otherPoint}
          </button>
        </StatusBlock>
      );
    }
    if (error?.code === 'NO_ACCESSIBLE_WALK' || error?.code === 'NO_WALK_ROUTE') {
      return (
        <StatusBlock title={ru.route.noWalkTitle} text={error.message}>
          <button type="button" className="button button--outline" onClick={chooseOtherPoints}>
            {ru.route.otherPoints}
          </button>
        </StatusBlock>
      );
    }
    return (
      <StatusBlock
        title={ru.route.failedTitle}
        text={error?.message ?? ru.errors.generic}
        onRetry={retry}
      />
    );
  }

  const data = plan.data;
  if (!data) return null;
  const best = data.journeys[0];
  if (data.status === 'no_transit' || !best) {
    return (
      <StatusBlock
        title={ru.route.noneTitle}
        text={lowFloorOnly ? ru.route.noneLowFloor : ru.route.noneAny}
      >
        <div className="button-row">
          <button type="button" className="button button--outline" onClick={retry}>
            {ru.route.refresh}
          </button>
          <button type="button" className="button button--outline" onClick={chooseOtherPoints}>
            {ru.route.otherPoints}
          </button>
        </div>
        {lowFloorOnly ? <a href={routeHref({ name: 'settings' })}>{ru.live.showAny}</a> : null}
      </StatusBlock>
    );
  }
  return (
    <JourneyView
      // Новый расчёт: начинаем с нового маршрута.
      key={plan.dataUpdatedAt}
      initial={best}
      points={points}
      lowFloorOnly={lowFloorOnly}
      onJourney={onJourney}
      onPlanAgain={retry}
    />
  );
}

function JourneyView({
  initial,
  points,
  lowFloorOnly,
  onJourney,
  onPlanAgain,
}: {
  initial: Journey;
  points: RoutePoints;
  lowFloorOnly: boolean;
  onJourney: (journey: Journey | null) => void;
  onPlanAgain: () => void;
}) {
  // Маршрут, который человек принял, и время прибытия, обещанное в момент выбора.
  const [base, setBase] = useState({ journey: initial, plannedArriveAt: initial.arriveAt });
  const [dismissed, setDismissed] = useState<string | null>(null);
  const check = useRouteCheck(points, lowFloorOnly, base.journey, base.plannedArriveAt);
  const now = useNow();

  // Тот же маршрут с новым временем показываем сразу: это те же машины.
  const current =
    check.data?.current && journeyKey(check.data.current) === journeyKey(base.journey)
      ? check.data.current
      : null;
  const shown = current ?? base.journey;

  useEffect(() => {
    onJourney(shown);
  }, [shown, onJourney]);
  useEffect(
    () => () => {
      onJourney(null);
    },
    [onJourney],
  );

  const result = check.data;
  const alternative = result?.alternative ?? null;
  const showChange =
    result !== undefined &&
    result.status !== 'ok' &&
    (alternative === null || journeyKey(alternative) !== dismissed);

  return (
    <section className="route" aria-label={ru.route.label}>
      <GreenBlock journey={shown} now={now} />
      {showChange ? (
        <ChangedBlock
          base={base}
          status={result.status}
          stoppedForS={result.stoppedForS}
          current={current}
          alternative={alternative}
          onAccept={() => {
            if (alternative)
              setBase({ journey: alternative, plannedArriveAt: alternative.arriveAt });
          }}
          onKeep={() => {
            if (alternative) setDismissed(journeyKey(alternative));
          }}
          onPlanAgain={onPlanAgain}
        />
      ) : null}
      <Timeline journey={shown} />
      <Steps journey={shown} now={now} />
      <p className="route__note">{ru.route.note}</p>
      <p className="route__note">{ru.map.attribution}</p>
    </section>
  );
}

function GreenBlock({ journey, now }: { journey: Journey; now: number }) {
  const plaque = journey.lowFloorOnly
    ? { text: ru.route.onlyLowFloor, warn: false }
    : hasNotLowFloor(journey)
      ? { text: ru.route.anyPartly, warn: true }
      : { text: ru.route.anyAllLow, warn: false };
  return (
    <div className="route-hero">
      <p className="route-hero__leave">{ru.route.leaveNow(formatTime(journey.departAt))}</p>
      {/* Крупная строка читается первой: какая машина и через сколько минут. */}
      <h2 className="route-hero__main">{headline(journey, now)}</h2>
      <p className="route-hero__arrive">{arrivalText(journey)}</p>
      <p className={`route-hero__plaque${plaque.warn ? ' route-hero__plaque--warn' : ''}`}>
        {plaque.text}
      </p>
    </div>
  );
}

function rideName(ride: RideStep): string {
  return lineName(ride.line.type, ride.line.number);
}

function ChangedBlock({
  base,
  status,
  stoppedForS,
  current,
  alternative,
  onAccept,
  onKeep,
  onPlanAgain,
}: {
  base: { journey: Journey; plannedArriveAt: string };
  status: 'stopped' | 'late' | 'gone';
  stoppedForS: number | null;
  current: Journey | null;
  alternative: Journey | null;
  onAccept: () => void;
  onKeep: () => void;
  onPlanAgain: () => void;
}) {
  const ride = firstRide(base.journey);
  const name = ride ? rideName(ride) : '';
  const headlineText =
    status === 'stopped'
      ? ru.route.stopped(name, Math.max(1, Math.round((stoppedForS ?? 0) / 60)))
      : status === 'late'
        ? ru.route.late(name)
        : ru.route.gone(name);
  return (
    <div className="route-changed" role="status">
      <p className="route-changed__title">{ru.route.changedTitle}</p>
      <p>
        <b>{headlineText}</b>{' '}
        {current && status !== 'gone'
          ? ru.route.wouldArrive(formatTime(current.arriveAt), formatTime(base.plannedArriveAt))
          : null}{' '}
        {alternative ? ru.route.better(formatTime(alternative.arriveAt)) : ru.route.noBetter}
      </p>
      {alternative ? (
        <div className="button-row">
          <button type="button" className="button button--primary" onClick={onAccept}>
            {ru.route.accept}
          </button>
          <button type="button" className="button button--outline" onClick={onKeep}>
            {ru.route.keep}
          </button>
        </div>
      ) : status === 'gone' ? (
        <button type="button" className="button button--outline" onClick={onPlanAgain}>
          {ru.route.findAgain}
        </button>
      ) : null}
    </div>
  );
}

function Timeline({ journey }: { journey: Journey }) {
  const segments = timeline(journey);
  const labels = segments.map(segmentLabel);
  return (
    <div className="route-card">
      <div className="timeline" role="img" aria-label={ru.route.timelineLabel(labels.join(', '))}>
        {segments.map((s, i) => (
          <div
            // Порядок кусков не меняется, пока маршрут тот же.
            key={i}
            className={`timeline__part timeline__part--${s.kind}`}
            style={
              {
                flexGrow: Math.max(1, Math.round(s.seconds / 60)),
                '--part-color': s.ride ? TYPE_COLOR[s.ride.line.type] : undefined,
              } as CSSProperties
            }
          />
        ))}
      </div>
      <p className="timeline__legend" aria-hidden="true">
        {segments.map((s, i) => (
          <span
            key={i}
            className={`timeline__label timeline__label--${s.kind}`}
            style={
              { '--part-color': s.ride ? TYPE_COLOR[s.ride.line.type] : undefined } as CSSProperties
            }
          >
            {labels[i]}
          </span>
        ))}
        <span>{ru.route.minutes}</span>
      </p>
    </div>
  );
}

function Steps({ journey, now }: { journey: Journey; now: number }) {
  return (
    <ol className="route-steps" aria-label={ru.route.stepsLabel}>
      {journey.steps.map((step, i) => (
        <li key={i} className="route-step">
          {step.kind === 'walk' ? (
            <WalkRow step={step} index={i} steps={journey.steps} />
          ) : (
            <RideRow step={step} journey={journey} now={now} />
          )}
        </li>
      ))}
    </ol>
  );
}

function WalkRow({
  step,
  index,
  steps,
}: {
  step: WalkStep;
  index: number;
  steps: readonly JourneyStep[];
}) {
  const next = steps[index + 1];
  const nextStop = next?.kind === 'ride' ? next.boardStop.name : null;
  const isTransfer = index > 0 && nextStop !== null;
  const title = nextStop
    ? isTransfer
      ? ru.route.walkTransfer(nextStop)
      : ru.route.walkToStop(nextStop)
    : ru.route.walkToEnd;
  return (
    <>
      <span className="route-step__icon route-step__icon--walk" aria-hidden="true">
        {ru.route.walkIcon}
      </span>
      <span className="route-step__text">
        <span className="route-step__title">{title}</span>
        <span className="route-step__sub">
          {ru.route.walkAbout(Math.round(step.distanceM / 10) * 10)}
          {step.hasStairs ? ` · ${ru.route.stairs}` : null}
        </span>
      </span>
      <span className="route-step__time">{ru.route.stepMinutes(minutesOf(step.durationS))}</span>
    </>
  );
}

function RideRow({ step, journey, now }: { step: RideStep; journey: Journey; now: number }) {
  const slack = transferSlackS(journey, step);
  const isFirst = firstRide(journey) === step;
  const rideS = Math.max(0, (Date.parse(step.arriveAt) - Date.parse(step.departAt)) / 1000);
  return (
    <>
      <Pill type={step.line.type} number={step.line.number} lowFloor={step.lowFloor} />
      <span className="route-step__text">
        <span className="route-step__title">{ru.route.rideTitle(rideName(step), step.toward)}</span>
        <span className="route-step__sub">
          {ru.route.board(step.boardStop.name, formatTime(step.departAt))}
        </span>
        <span className="route-step__sub">
          {ru.route.alight(step.alightStop.name, stopsText(step.stopsCount))}
        </span>
        <span className="route-step__sub">
          {isFirst
            ? ru.route.arrivesIn(minutesUntil(step.departAt, now))
            : slack !== null
              ? ru.route.transferSlack(Math.floor(slack / 60))
              : null}{' '}
          <LowFloorBadge value={step.lowFloor} />
        </span>
        {isFirst ? (
          <span className="route-step__sub">
            {ru.route.away(typeName(step.line.type).toLowerCase(), step.stopsAway)}
          </span>
        ) : null}
      </span>
      <span className="route-step__time">{ru.route.stepMinutes(minutesOf(rideS))}</span>
    </>
  );
}
