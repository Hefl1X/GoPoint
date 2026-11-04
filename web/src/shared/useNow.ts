// Текущее время для подписей «через N мин»: обновляется раз в 30 с,
// в скрытой вкладке не тикает (браузер сам замедляет таймеры).
import { useEffect, useState } from 'react';

export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, intervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [intervalMs]);
  return now;
}
