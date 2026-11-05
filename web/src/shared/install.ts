// Предложение установить сайт на экран телефона: режим браузера и «Не сейчас».
import { useCallback, useSyncExternalStore } from 'react';
import type { InstallMode } from '../ports/Installer';
import { useServices } from './services';

const DISMISSED_KEY = 'gopoint.install.dismissed';

export function useInstallMode(): InstallMode {
  const { installer } = useServices();
  return useSyncExternalStore(
    (onChange) => installer.subscribe(onChange),
    () => installer.mode(),
  );
}

/** Баннер после первого маршрута: пока человек не нажал «Не сейчас» или не установил. */
export function useInstallOffer(): {
  readonly mode: InstallMode;
  readonly dismissed: boolean;
  readonly dismiss: () => void;
} {
  const { store } = useServices();
  const mode = useInstallMode();
  const dismissed = useSyncExternalStore(
    subscribeDismissed,
    () => store.get(DISMISSED_KEY) === '1',
  );
  const dismiss = useCallback(() => {
    store.set(DISMISSED_KEY, '1');
    for (const l of dismissListeners) l();
  }, [store]);
  return { mode, dismissed, dismiss };
}

const dismissListeners = new Set<() => void>();
function subscribeDismissed(onChange: () => void) {
  dismissListeners.add(onChange);
  return () => {
    dismissListeners.delete(onChange);
  };
}
