// Предложение установить GoPoint на экран телефона. Показывается после первого
// построенного маршрута (docs/DESIGN.md): на Android окно браузера, на iPhone инструкция.
import { useInstallOffer } from '../../shared/install';
import { routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useServices } from '../../shared/services';

export function InstallBanner() {
  const { installer } = useServices();
  const { mode, dismissed, dismiss } = useInstallOffer();
  if (dismissed || (mode !== 'prompt' && mode !== 'ios')) return null;
  return (
    <section className="install-banner" aria-labelledby="install-title">
      <p className="install-banner__title" id="install-title">
        {ru.install.title}
      </p>
      <p>{ru.install.text}</p>
      <div className="install-banner__actions">
        {mode === 'prompt' ? (
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              void installer.prompt();
            }}
          >
            {ru.install.install}
          </button>
        ) : (
          <a className="button button--primary" href={routeHref({ name: 'install' })}>
            {ru.install.how}
          </a>
        )}
        <button type="button" className="button button--outline" onClick={dismiss}>
          {ru.install.notNow}
        </button>
      </div>
    </section>
  );
}
