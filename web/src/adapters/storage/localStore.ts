// Память устройства на localStorage. В приватном режиме или при запрете
// хранилища сайт продолжает работать, просто ничего не запоминает.
import type { KeyValueStore } from '../../ports/Storage';

export function createLocalStore(): KeyValueStore {
  return {
    get(key) {
      try {
        return window.localStorage.getItem(key);
      } catch {
        // Хранилище недоступно (приватный режим, запрет): работаем без памяти.
        return null;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch {
        // Хранилище недоступно или переполнено: выбор действует до закрытия вкладки.
        return;
      }
    },
  };
}

/** Память на время сеанса: для тестов и как запасной вариант. */
export function createMemoryStore(initial: Record<string, string> = {}): KeyValueStore {
  const data = new Map(Object.entries(initial));
  return {
    get: (key) => data.get(key) ?? null,
    set: (key, value) => {
      data.set(key, value);
    },
  };
}
