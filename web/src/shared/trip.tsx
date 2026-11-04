// Точки А и Б. Хранятся только в памяти открытой страницы: адреса человека
// не записываются на устройство и не отправляются никуда, кроме расчёта.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { Endpoint, TripPoint } from '../domain/types';

interface TripValue {
  readonly from: TripPoint | null;
  readonly to: TripPoint | null;
  readonly setPoint: (end: Endpoint, point: TripPoint | null) => void;
  readonly swap: () => void;
}

const TripContext = createContext<TripValue | null>(null);

export function TripProvider({
  children,
  initial = {},
}: {
  children: ReactNode;
  initial?: { from?: TripPoint | null; to?: TripPoint | null } | undefined;
}) {
  const [points, setPoints] = useState<{ from: TripPoint | null; to: TripPoint | null }>({
    from: initial.from ?? null,
    to: initial.to ?? null,
  });
  const setPoint = useCallback((end: Endpoint, point: TripPoint | null) => {
    setPoints((p) => ({ ...p, [end]: point }));
  }, []);
  const swap = useCallback(() => {
    setPoints((p) => ({ from: p.to, to: p.from }));
  }, []);
  const value = useMemo(
    () => ({ from: points.from, to: points.to, setPoint, swap }),
    [points, setPoint, swap],
  );
  return <TripContext.Provider value={value}>{children}</TripContext.Provider>;
}

export function useTrip(): TripValue {
  const value = useContext(TripContext);
  if (!value) throw new Error('TripProvider не подключён');
  return value;
}
