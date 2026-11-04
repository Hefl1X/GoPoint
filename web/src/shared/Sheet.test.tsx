import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Sheet } from './Sheet';

function setup() {
  render(
    <Sheet label="Панель">
      <a href="#/about">О приложении</a>
    </Sheet>,
  );
  return screen.getByRole('button', { name: 'Свернуть панель' });
}

describe('нижняя панель', () => {
  it('нажатие на ручку сворачивает и разворачивает', () => {
    const grip = setup();
    expect(grip).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(grip);
    expect(screen.getByRole('button', { name: 'Развернуть панель' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Развернуть панель' }));
    expect(screen.getByRole('button', { name: 'Свернуть панель' })).toBeInTheDocument();
  });

  it('потянуть вниз — свернуть, вверх — развернуть', () => {
    const grip = setup();
    fireEvent.pointerDown(grip, { clientY: 500, pointerId: 1 });
    fireEvent.pointerMove(grip, { clientY: 600, pointerId: 1 });
    fireEvent.pointerUp(grip, { clientY: 600, pointerId: 1 });
    fireEvent.click(grip); // браузер присылает click после перетаскивания: не должен отменить
    const collapsed = screen.getByRole('button', { name: 'Развернуть панель' });
    fireEvent.pointerDown(collapsed, { clientY: 600, pointerId: 1 });
    fireEvent.pointerMove(collapsed, { clientY: 480, pointerId: 1 });
    fireEvent.pointerUp(collapsed, { clientY: 480, pointerId: 1 });
    expect(screen.getByRole('button', { name: 'Свернуть панель' })).toBeInTheDocument();
  });

  it('короткое движение не сворачивает', () => {
    const grip = setup();
    fireEvent.pointerDown(grip, { clientY: 500, pointerId: 1 });
    fireEvent.pointerMove(grip, { clientY: 520, pointerId: 1 });
    fireEvent.pointerUp(grip, { clientY: 520, pointerId: 1 });
    expect(screen.getByRole('button', { name: 'Свернуть панель' })).toBeInTheDocument();
  });

  it('содержимое свёрнутой панели недоступно для фокуса', () => {
    const grip = setup();
    fireEvent.click(grip);
    expect(screen.getByText('О приложении').closest('[inert]')).not.toBeNull();
  });
});
