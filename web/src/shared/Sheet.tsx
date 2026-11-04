// Нижняя панель поверх карты. Тянешь за ручку вниз — сворачивается до полоски,
// вверх — разворачивается. Нажатие на ручку (и клавиатура) делает то же самое.
import { useRef, useState, type PointerEvent, type ReactNode } from 'react';
import { ru } from './ru';

// Насколько нужно потянуть, чтобы панель свернулась или развернулась.
const SWIPE_PX = 40;
// Меньше этого сдвига считаем нажатием, а не перетаскиванием.
const TAP_PX = 6;

export function Sheet({ label, children }: { label?: string | undefined; children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [drag, setDrag] = useState(0);
  const startY = useRef<number | null>(null);
  const moved = useRef(false);

  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    startY.current = event.clientY;
    moved.current = false;
    // Палец продолжает «держать» ручку, даже если ушёл за её край.
    // В старых браузерах и в тестовой среде этой функции нет: тогда без неё.
    const grip = event.currentTarget as Partial<Pick<HTMLElement, 'setPointerCapture'>>;
    if (typeof grip.setPointerCapture === 'function') {
      grip.setPointerCapture.call(event.currentTarget, event.pointerId);
    }
  };

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (startY.current === null) return;
    const dy = event.clientY - startY.current;
    if (Math.abs(dy) > TAP_PX) moved.current = true;
    // Открытую панель тянем только вниз, свёрнутую только вверх.
    setDrag(collapsed ? Math.min(0, dy) : Math.max(0, dy));
  };

  const onPointerUp = (event: PointerEvent<HTMLButtonElement>) => {
    if (startY.current === null) return;
    const dy = event.clientY - startY.current;
    startY.current = null;
    setDrag(0);
    if (dy > SWIPE_PX) setCollapsed(true);
    else if (dy < -SWIPE_PX) setCollapsed(false);
  };

  const transform = collapsed
    ? `translateY(calc(100% - var(--sheet-peek) + ${String(drag)}px))`
    : drag > 0
      ? `translateY(${String(drag)}px)`
      : undefined;

  return (
    <section
      className={`sheet${collapsed ? ' sheet--collapsed' : ''}${drag !== 0 ? ' sheet--dragging' : ''}`}
      aria-label={label}
      style={transform ? { transform } : undefined}
    >
      <button
        type="button"
        className="sheet__grip"
        aria-expanded={!collapsed}
        aria-label={collapsed ? ru.sheet.expand : ru.sheet.collapse}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          startY.current = null;
          setDrag(0);
        }}
        onClick={() => {
          // После перетаскивания браузер тоже присылает click: его пропускаем.
          if (moved.current) {
            moved.current = false;
            return;
          }
          setCollapsed((value) => !value);
        }}
      >
        <span className="sheet__handle" aria-hidden="true" />
      </button>
      <div className="sheet__body" inert={collapsed}>
        {children}
      </div>
    </section>
  );
}
