// Установка сайта на экран телефона: событие beforeinstallprompt (Chrome на Android)
// и инструкция для Safari на iPhone. Регистрация service worker (vite-plugin-pwa).
import { registerSW } from 'virtual:pwa-register';
import type { InstallMode, Installer } from '../../ports/Installer';

// Событие Chrome; в стандартных типах DOM его нет.
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

function isStandalone(): boolean {
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || window.matchMedia('(display-mode: standalone)').matches;
}

function isIos(): boolean {
  const ua = navigator.userAgent;
  // iPadOS называет себя Mac, но у него есть сенсорный экран.
  return /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

export function createBrowserInstaller(): Installer {
  let deferred: BeforeInstallPromptEvent | null = null;
  let installed = isStandalone();
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const listener of listeners) listener();
  };

  window.addEventListener('beforeinstallprompt', (event) => {
    // Своё окно не показываем сразу: предложим после первого построенного маршрута.
    event.preventDefault();
    deferred = event as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener('appinstalled', () => {
    deferred = null;
    installed = true;
    notify();
  });

  return {
    mode(): InstallMode {
      if (installed) return 'installed';
      if (deferred) return 'prompt';
      if (isIos()) return 'ios';
      return 'unsupported';
    },
    subscribe(onChange) {
      listeners.add(onChange);
      return () => {
        listeners.delete(onChange);
      };
    },
    async prompt() {
      const event = deferred;
      if (!event) return false;
      // Окно браузера показывается один раз на событие.
      deferred = null;
      await event.prompt();
      const choice = await event.userChoice;
      notify();
      return choice.outcome === 'accepted';
    },
  };
}

/**
 * Service worker: сохраняет оболочку сайта и справочники для работы без сети.
 * Работает только по https (или на localhost): по адресу Wi-Fi без https браузер его не включит.
 */
export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) return;
  void registerSW({ immediate: true });
}
