// Порт установки сайта на экран телефона (PWA). Реализация: adapters/pwa.

/**
 * prompt — браузер (Android, Chrome) может показать своё окно «Установить»;
 * ios — iPhone и iPad: установить можно только вручную через Safari, показываем инструкцию;
 * installed — сайт уже открыт как приложение с экрана телефона;
 * unsupported — установить нельзя или браузер ещё не разрешил (тогда ничего не предлагаем).
 */
export type InstallMode = 'prompt' | 'ios' | 'installed' | 'unsupported';

export interface Installer {
  mode(): InstallMode;
  /** Сообщает, когда mode() поменялся (браузер разрешил установку или её завершили). */
  subscribe(onChange: () => void): () => void;
  /** Показать окно браузера «Установить». true — человек согласился. */
  prompt(): Promise<boolean>;
}
