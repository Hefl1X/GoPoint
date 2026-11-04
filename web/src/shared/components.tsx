// Общие элементы интерфейса GoPoint.
import type { UseQueryResult } from '@tanstack/react-query';
import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { MUTED_COLOR, TYPE_COLOR, lowFloorLabel } from '../domain/transport';
import type { Accessibility, TransportType } from '../domain/types';
import { ApiError } from '../ports/LiveApi';
import { routeHref, type Route } from './router';
import { ru } from './ru';

/** Номер маршрута в цветной «таблетке». Без низкого пола: только контур (форма, не только цвет). */
export function Pill({
  type,
  number,
  lowFloor = 'yes',
  muted = false,
  large = false,
}: {
  type: TransportType;
  number: string;
  lowFloor?: Accessibility;
  muted?: boolean;
  large?: boolean;
}) {
  const color = muted ? MUTED_COLOR : TYPE_COLOR[type];
  const classes = ['pill', lowFloor === 'yes' ? '' : 'pill--outline', large ? 'pill--large' : '']
    .filter(Boolean)
    .join(' ');
  return (
    <span className={classes} style={{ '--pill-color': color } as CSSProperties} aria-hidden="true">
      {number}
    </span>
  );
}

/** Пометка «низкий пол» / «не низкий пол» / «низкий пол не указан». */
export function LowFloorBadge({ value }: { value: Accessibility }) {
  return (
    <span className={`badge ${value === 'yes' ? 'badge--yes' : 'badge--warn'}`}>
      {lowFloorLabel(value)}
    </span>
  );
}

/** Заголовок экрана; получает фокус при открытии экрана (для экранной читалки). */
export function ScreenTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div className="screen-title">
      <h1 ref={ref} tabIndex={-1}>
        {children}
      </h1>
      {sub ? <p className="screen-title__sub">{sub}</p> : null}
    </div>
  );
}

export function BackButton() {
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={ru.back}
      onClick={() => {
        if (window.history.length > 1) window.history.back();
        else window.location.hash = '#/';
      }}
    >
      <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
        <path
          d="M15 5l-7 7 7 7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );
}

type Tab = 'map' | 'transport' | 'settings';

const TAB_ROUTE: Record<Tab, Route> = {
  map: { name: 'map', vehicleId: null },
  transport: { name: 'transport' },
  settings: { name: 'settings' },
};

const TAB_ICON: Record<Tab, ReactNode> = {
  map: <path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15" />,
  transport: (
    <>
      <rect x="5" y="3" width="14" height="15" rx="3" />
      <path d="M5 11h14M8 18v3M16 18v3" />
      <circle cx="9" cy="14.5" r="0.6" />
      <circle cx="15" cy="14.5" r="0.6" />
    </>
  ),
  settings: <path d="M4 7h10M18 7h2M4 17h4M12 17h8M16 5v4M10 15v4" />,
};

export function BottomNav({ active }: { active: Tab }) {
  return (
    <nav className="bottom-nav" aria-label={ru.nav.label}>
      {(['map', 'transport', 'settings'] as const).map((tab) => (
        <a
          key={tab}
          href={routeHref(TAB_ROUTE[tab])}
          className="bottom-nav__item"
          aria-current={tab === active ? 'page' : undefined}
        >
          <span className="bottom-nav__icon">
            <svg
              viewBox="0 0 24 24"
              width="24"
              height="24"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              {TAB_ICON[tab]}
            </svg>
          </span>
          <span>{ru.nav[tab]}</span>
        </a>
      ))}
    </nav>
  );
}

/** Серый блок без жёлтых плашек: загрузка, нет данных, ошибка, нет сети. */
export function StatusBlock({
  title,
  text,
  onRetry,
  children,
  busy = false,
}: {
  title?: string;
  text?: string;
  onRetry?: () => void;
  children?: ReactNode;
  busy?: boolean;
}) {
  return (
    <div className="status-block" role="status" aria-busy={busy}>
      {title ? <p className="status-block__title">{title}</p> : null}
      {text ? <p>{text}</p> : null}
      {children}
      {onRetry ? (
        <button type="button" className="button button--outline" onClick={onRetry}>
          {ru.retry}
        </button>
      ) : null}
    </div>
  );
}

/**
 * Состояния экрана с данными: загрузка, нет сети, ошибка. Если данные есть,
 * показывает их (render). Пустоту экран решает сам.
 */
export function LiveState<T>({
  query,
  data,
  online,
  render,
}: {
  query: UseQueryResult<T>;
  data: T | undefined;
  online: boolean;
  render: (data: T) => ReactNode;
}) {
  if (data !== undefined) return <>{render(data)}</>;
  const retry = () => {
    void query.refetch();
  };
  if (!online)
    return <StatusBlock title={ru.errors.offlineTitle} text={ru.errors.offline} onRetry={retry} />;
  if (query.isError) {
    const message = query.error instanceof ApiError ? query.error.message : ru.errors.generic;
    if (query.error instanceof ApiError && query.error.code === 'NETWORK') {
      return (
        <StatusBlock title={ru.errors.offlineTitle} text={ru.errors.offline} onRetry={retry} />
      );
    }
    return <StatusBlock text={message} onRetry={retry} />;
  }
  if (query.isPending || query.isFetching) return <StatusBlock text={ru.loading} busy />;
  // Данные были, но устарели: просим обновить.
  return <StatusBlock text={ru.errors.generic} onRetry={retry} />;
}
