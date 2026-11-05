// Как установить GoPoint на iPhone: Safari, «Поделиться», «На экран „Домой“».
import { useEffect, useRef } from 'react';
import { BackButton } from '../../shared/components';
import { ru } from '../../shared/ru';

export function InstallIosScreen() {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <main className="screen">
      <div className="screen-head">
        <BackButton />
        <h1 ref={heading} tabIndex={-1}>
          {ru.install.iosTitle}
        </h1>
      </div>
      <p>{ru.install.iosIntro}</p>
      <ol className="install-steps">
        {ru.install.iosSteps.map((step, i) => (
          <li key={step}>
            <span className="install-steps__num" aria-hidden="true">
              {i + 1}
            </span>
            <span>{step}</span>
          </li>
        ))}
      </ol>
      <p className="route__note">{ru.install.iosNote}</p>
    </main>
  );
}
