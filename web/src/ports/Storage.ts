// Порт памяти устройства. Реализация: adapters/storage (localStorage),
// позже может быть хранилище Capacitor.
export interface KeyValueStore {
  get(key: string): string | null;
  set(key: string, value: string): void;
}
