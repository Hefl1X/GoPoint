// Запасной вид без карты: список машин. Нужен, если браузер не умеет WebGL,
// и для проверок. Полностью доступен с клавиатуры и для экранной читалки.
import { lineName, lowFloorLabel, TYPE_COLOR, MUTED_COLOR } from '../../domain/transport';
import type { MapViewProps } from '../../ports/MapView';

const END_NAME = { from: 'Точка А', to: 'Точка Б' } as const;

export function ListMapView({
  label,
  vehicles,
  selectedVehicleId,
  tripPoints,
  onVehicleSelect,
  note = 'Карта недоступна на этом устройстве.',
}: MapViewProps & { readonly note?: string }) {
  const sorted = [...vehicles].sort(
    (a, b) =>
      Number(a.muted) - Number(b.muted) ||
      a.number.localeCompare(b.number, 'ru', { numeric: true }) ||
      a.id.localeCompare(b.id),
  );
  return (
    <section className="map-list" aria-label={label} data-testid="map-list">
      <p className="map-list__note" role="status">
        {note}
      </p>
      {tripPoints.length > 0 ? (
        <ul className="map-list__trip">
          {tripPoints.map((p) => (
            <li key={p.end}>
              {END_NAME[p.end]}: {p.label}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="map-list__note">Транспорт на линии:</p>
      <ul className="map-list__items">
        {sorted.map((v) => (
          <li key={v.id}>
            <button
              type="button"
              className="map-list__item"
              aria-pressed={v.id === selectedVehicleId}
              onClick={() => {
                onVehicleSelect(v.id);
              }}
            >
              <span
                className={`pill${v.lowFloor === 'yes' ? '' : ' pill--outline'}`}
                style={
                  {
                    '--pill-color': v.muted ? MUTED_COLOR : TYPE_COLOR[v.type],
                  } as React.CSSProperties
                }
                aria-hidden="true"
              >
                {v.number}
              </span>
              <span>
                {lineName(v.type, v.number)}, {lowFloorLabel(v.lowFloor)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
