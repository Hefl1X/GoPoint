// «О приложении»: версия, что значит «время ориентировочное», источники, местоположение.
import { BackButton } from '../../shared/components';
import { useMeta } from '../../shared/queries';
import { ru } from '../../shared/ru';
import { useEffect, useRef } from 'react';

const APP_VERSION = '0.1.0';

export function AboutScreen() {
  const meta = useMeta();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  const sections: [string, string][] = [
    [ru.about.app, `${ru.appName} · ${ru.about.version} ${meta.data?.version ?? APP_VERSION}`],
    [ru.about.approxTitle, ru.about.approx],
    [ru.about.sourcesTitle, ru.about.sources],
    [ru.about.locationTitle, ru.about.location],
  ];
  return (
    <main className="screen">
      <div className="screen-head">
        <BackButton />
        <h1 ref={heading} tabIndex={-1}>
          {ru.about.title}
        </h1>
      </div>
      {sections.map(([title, text]) => (
        <section key={title} className="card">
          <h2 className="card__title">{title}</h2>
          <p>{text}</p>
        </section>
      ))}
    </main>
  );
}
