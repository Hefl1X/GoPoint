// Настройки пользователя. «Низкопольный транспорт» по умолчанию включена,
// выбор запоминается на устройстве.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { useServices } from './services';

const LOW_FLOOR_KEY = 'gopoint.lowFloorOnly';

interface SettingsValue {
  readonly lowFloorOnly: boolean;
  readonly setLowFloorOnly: (value: boolean) => void;
}

const SettingsContext = createContext<SettingsValue | null>(null);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const { store } = useServices();
  // Включена всегда, кроме явно сохранённого «false».
  const [lowFloorOnly, setState] = useState(() => store.get(LOW_FLOOR_KEY) !== 'false');
  const setLowFloorOnly = useCallback(
    (value: boolean) => {
      setState(value);
      store.set(LOW_FLOOR_KEY, String(value));
    },
    [store],
  );
  const value = useMemo(() => ({ lowFloorOnly, setLowFloorOnly }), [lowFloorOnly, setLowFloorOnly]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings(): SettingsValue {
  const value = useContext(SettingsContext);
  if (!value) throw new Error('SettingsProvider не подключён');
  return value;
}
