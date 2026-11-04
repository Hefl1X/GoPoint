// Настройки: первой строкой «Низкопольный транспорт».
import { Pill, ScreenTitle } from '../../shared/components';
import { routeHref } from '../../shared/router';
import { ru } from '../../shared/ru';
import { useSettings } from '../../shared/settings';

export function SettingsScreen() {
  const { lowFloorOnly, setLowFloorOnly } = useSettings();
  return (
    <main className="screen">
      <ScreenTitle>{ru.settings.title}</ScreenTitle>
      <div className="card setting">
        <div>
          <p className="setting__label" id="low-floor-label">
            {ru.settings.lowFloor}
          </p>
          <p className="muted" id="low-floor-hint">
            {ru.settings.lowFloorHint}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          className="switch"
          aria-checked={lowFloorOnly}
          aria-labelledby="low-floor-label"
          aria-describedby="low-floor-hint"
          onClick={() => {
            setLowFloorOnly(!lowFloorOnly);
          }}
        >
          <span className="switch__thumb" aria-hidden="true" />
        </button>
      </div>
      <section className="card legend" aria-labelledby="legend-title">
        <h2 className="card__title" id="legend-title">
          {ru.settings.legendTitle}
        </h2>
        <ul className="legend__list">
          <li>
            <Pill type="bus" number="8" lowFloor="yes" />
            <span>{ru.settings.legendYes}</span>
          </li>
          <li>
            <Pill type="bus" number="8" lowFloor="no" />
            <span>{ru.settings.legendNo}</span>
          </li>
        </ul>
        <p className="muted">{ru.settings.legendHint}</p>
      </section>
      <a className="card card--link" href={routeHref({ name: 'about' })}>
        {ru.settings.about}
      </a>
    </main>
  );
}
