// «Транспорт сейчас»: маршруты с числом машин на линии, фильтр по виду, поиск по номеру.
import { useState } from 'react';
import {
  TRANSPORT_TYPES,
  filterLines,
  lineName,
  typePlural,
  vehiclesOnLineText,
} from '../../domain/transport';
import type { TransportType } from '../../domain/types';
import { LiveState, Pill, ScreenTitle, StatusBlock } from '../../shared/components';
import { useLines, useOnline } from '../../shared/queries';
import { routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useSettings } from '../../shared/settings';

export function LiveRoutesScreen() {
  const { lowFloorOnly } = useSettings();
  const online = useOnline();
  const lines = useLines(lowFloorOnly);
  const [type, setType] = useState<TransportType | 'all'>('all');
  const [query, setQuery] = useState('');

  return (
    <main className="screen">
      <ScreenTitle sub={ru.transport.subtitle}>{ru.transport.title}</ScreenTitle>
      <label className="visually-hidden" htmlFor="line-search">
        {ru.transport.search}
      </label>
      <input
        id="line-search"
        className="input"
        type="search"
        inputMode="search"
        autoComplete="off"
        placeholder={ru.transport.search}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
        }}
      />
      <div className="chips" role="group" aria-label={ru.transport.filterLabel}>
        {(['all', ...TRANSPORT_TYPES] as const).map((t) => (
          <button
            key={t}
            type="button"
            className="chip"
            aria-pressed={type === t}
            onClick={() => {
              setType(t);
            }}
          >
            {t === 'all' ? ru.transport.all : typePlural(t)}
          </button>
        ))}
      </div>
      <LiveState
        query={lines.query}
        data={lines.data}
        online={online}
        render={(all) => {
          const shown = filterLines(all, { type, query, lowFloorOnly });
          if (all.every((l) => l.vehiclesOnLine === 0)) {
            return (
              <StatusBlock
                title={ru.live.noneTitle}
                text={lowFloorOnly ? ru.live.noneLowFloor : ru.live.noneAny}
              >
                {lowFloorOnly ? (
                  <a href={routeHref({ name: 'settings' })}>{ru.live.showAny}</a>
                ) : null}
              </StatusBlock>
            );
          }
          if (shown.length === 0) return <StatusBlock text={ru.transport.nothingFound} />;
          return (
            <ul className="card-list">
              {shown.map(({ line, vehiclesOnLine }) => (
                <li key={line.id}>
                  <a className="line-row" href={routeHref({ name: 'line', lineId: line.id })}>
                    <Pill type={line.type} number={line.number} large />
                    <span className="line-row__text">
                      <span className="line-row__name">{lineName(line.type, line.number)}</span>
                      <span className="muted">{line.title}</span>
                    </span>
                    {vehiclesOnLine > 0 ? (
                      <span className="badge badge--yes">{vehiclesOnLineText(vehiclesOnLine)}</span>
                    ) : (
                      <span className="badge badge--grey">{ru.transport.notOnLine}</span>
                    )}
                  </a>
                </li>
              ))}
            </ul>
          );
        }}
      />
    </main>
  );
}
