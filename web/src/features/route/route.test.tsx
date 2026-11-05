// Экран маршрута: найден, нет транспорта, ошибки, пересчёт с решением человека.
import { act, fireEvent, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Journey, RouteCheck } from '../../domain/journey';
import { ApiError } from '../../ports/LiveApi';
import { createMemoryStore } from '../../adapters/storage/localStore';
import { fakeApi, fakeInstaller, inMinutes, journey, renderApp } from '../../test-utils';
import { MapScreen } from '../start/MapScreen';

const TRIP = {
  from: { label: 'Аура', point: { lat: 55.04, lon: 82.92 } },
  to: { label: 'Цирк', point: { lat: 55.05, lon: 82.91 } },
};

afterEach(() => {
  window.location.hash = '';
  vi.useRealTimers();
});

function renderRoute(api = fakeApi()) {
  return renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, { api, trip: TRIP });
}

describe('маршрут найден', () => {
  it('зелёный блок, шкала, шаги, пометка', async () => {
    renderRoute();
    const route = await screen.findByRole('region', { name: 'Маршрут' });
    expect(within(route).getByRole('heading', { name: /^Автобус 3 · (9|10) мин$/ })).toBeVisible();
    expect(within(route).getByText(/^Выехать сейчас · \d\d:\d\d$/)).toBeVisible();
    expect(
      within(route).getByText(/^Приедете в \d\d:\d\d · 26 минут в пути · без пересадок$/),
    ).toBeVisible();
    expect(within(route).getByText('Построен только по низкопольным рейсам')).toBeVisible();
    expect(
      within(route).getByRole('img', {
        name: 'Шкала времени, минуты: пешком 6, ожидание 4, автобус 12, пешком 4',
      }),
    ).toBeVisible();
    const steps = within(route).getAllByRole('listitem');
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent('Пешком до остановки «Университет»');
    expect(steps[0]).toHaveTextContent('≈ 290 м');
    expect(steps[1]).toHaveTextContent('Автобус 3, в сторону «Северный»');
    expect(steps[1]).toHaveTextContent('Выйти на «Площадь Маркса», 7 остановок');
    expect(steps[1]).toHaveTextContent('автобус в 2 остановках от вас');
    expect(steps[1]).toHaveTextContent('низкий пол');
    expect(steps[2]).toHaveTextContent('Пешком до точки Б');
    expect(
      within(route).getByText(
        'Время ориентировочное, без учёта пробок впереди. Маршрут построен по данным карты, состояние тротуаров не гарантируется.',
      ),
    ).toBeVisible();
  });

  it('любой транспорт: плашка и пометка «не низкий пол» у машины', async () => {
    const api = fakeApi({
      planRoute: vi.fn(() => {
        const j = journey({ lowFloorOnly: false });
        const steps = j.steps.map((s) =>
          s.kind === 'ride' ? { ...s, lowFloor: 'no' as const } : s,
        );
        return Promise.resolve({ status: 'ok' as const, journeys: [{ ...j, steps }] });
      }),
    });
    renderRoute(api);
    const route = await screen.findByRole('region', { name: 'Маршрут' });
    expect(within(route).getByText('Любой транспорт: часть рейсов не низкопольная')).toBeVisible();
    expect(within(route).getAllByRole('listitem')[1]).toHaveTextContent('не низкий пол');
  });

  it('лестница на пешем участке названа словами', async () => {
    const api = fakeApi({
      planRoute: vi.fn(() => {
        const j = journey();
        const steps = j.steps.map((s, i) =>
          i === 0 && s.kind === 'walk' ? { ...s, hasStairs: true } : s,
        );
        return Promise.resolve({ status: 'ok' as const, journeys: [{ ...j, steps }] });
      }),
    });
    renderRoute(api);
    const route = await screen.findByRole('region', { name: 'Маршрут' });
    expect(within(route).getAllByRole('listitem')[0]).toHaveTextContent(
      'на пути есть лестница или эскалатор',
    );
  });
});

describe('нет маршрута и ошибки', () => {
  it('транспорта нет: серый блок, «Обновить», «Выбрать другие точки», без пешего маршрута', async () => {
    const planRoute = vi.fn(() => Promise.resolve({ status: 'no_transit' as const, journeys: [] }));
    renderRoute(fakeApi({ planRoute }));
    expect(await screen.findByText('Транспорта сейчас нет')).toBeVisible();
    expect(screen.queryByRole('region', { name: 'Маршрут' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Показать любой транспорт' })).toHaveAttribute(
      'href',
      '#/settings',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Обновить' }));
    await vi.waitFor(() => {
      expect(planRoute).toHaveBeenCalledTimes(2);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать другие точки' }));
    expect(window.location.hash).toBe('#/search/to');
  });

  it('нет сети: точки сохранены, «Повторить»', async () => {
    const planRoute = vi.fn(() =>
      Promise.reject(new ApiError(0, 'NETWORK', 'Нет подключения к интернету.')),
    );
    renderRoute(fakeApi({ planRoute }));
    expect(await screen.findByText('Нет подключения к интернету')).toBeVisible();
    expect(screen.getByText(/введённые точки сохранены/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Откуда: Аура' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    await vi.waitFor(() => {
      expect(planRoute).toHaveBeenCalledTimes(2);
    });
  });

  it('точка вне города', async () => {
    const planRoute = vi.fn(() =>
      Promise.reject(new ApiError(422, 'OUTSIDE_CITY', 'Эта точка за пределами Новосибирска.')),
    );
    renderRoute(fakeApi({ planRoute }));
    expect(await screen.findByText('Точка вне Новосибирска')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Выбрать другую точку' })).toBeVisible();
  });

  it('к точке только по лестнице: сообщение сервера и выбор других точек', async () => {
    const message =
      'Отсюда нашёлся путь только по лестнице или эскалатору. Выберите точку ближе к улице.';
    const planRoute = vi.fn(() => Promise.reject(new ApiError(422, 'NO_ACCESSIBLE_WALK', message)));
    renderRoute(fakeApi({ planRoute }));
    expect(await screen.findByText(message)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Выбрать другие точки' })).toBeVisible();
  });

  it('загрузка: «Ищем маршрут…» и отмена поиска', async () => {
    const planRoute = vi.fn(
      (_p: unknown, _l: boolean, signal?: AbortSignal) =>
        new Promise<never>((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            reject(new DOMException('отмена', 'AbortError'));
          });
        }),
    );
    renderRoute(fakeApi({ planRoute }));
    expect(await screen.findByText('Ищем маршрут…')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить поиск' }));
    expect(await screen.findByText('Поиск отменён')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Искать снова' })).toBeVisible();
  });
});

describe('пересчёт', () => {
  it('машина стоит: «Маршрут изменился», новый маршрут только по нажатию', async () => {
    const start = Date.now();
    const alternative: Journey = journey(
      {
        arriveAt: inMinutes(24, start),
        steps: journey({}, start).steps.map((s) =>
          s.kind === 'ride'
            ? { ...s, vehicleId: 'bus-36-1', line: { ...s.line, id: 'bus-36', number: '36' } }
            : s,
        ),
      },
      start,
    );
    const checkRoute = vi.fn((_p: unknown, _l: boolean, current: Journey): Promise<RouteCheck> =>
      Promise.resolve(
        current.steps.some((s) => s.kind === 'ride' && s.vehicleId === 'bus-3-1')
          ? {
              status: 'stopped',
              stoppedForS: 9 * 60,
              current: { ...current, arriveAt: inMinutes(35, start) },
              alternative,
            }
          : { status: 'ok', stoppedForS: null, current, alternative: null },
      ),
    );
    renderRoute(fakeApi({ checkRoute }));
    expect(await screen.findByText('Маршрут изменился')).toBeVisible();
    expect(screen.getByText('Автобус 3 стоит на месте уже 9 минут.')).toBeVisible();
    // Маршрут молча не заменён.
    expect(screen.getByRole('heading', { name: /^Автобус 3 · / })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Принять новый' }));
    expect(await screen.findByRole('heading', { name: /^Автобус 36 · / })).toBeVisible();
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByText('Маршрут изменился')).toBeNull();
  });

  it('«Оставить прежний» убирает предложение, маршрут тот же', async () => {
    const checkRoute = vi.fn((_p: unknown, _l: boolean, current: Journey): Promise<RouteCheck> =>
      Promise.resolve({
        status: 'late',
        stoppedForS: null,
        current,
        alternative: journey({
          steps: journey().steps.map((s) =>
            s.kind === 'ride' ? { ...s, vehicleId: 'bus-3-7' } : s,
          ),
        }),
      }),
    );
    renderRoute(fakeApi({ checkRoute }));
    expect(await screen.findByText('Автобус 3 задерживается.')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Оставить прежний' }));
    expect(screen.queryByText('Маршрут изменился')).toBeNull();
    expect(screen.getByRole('heading', { name: /^Автобус 3 · / })).toBeVisible();
  });
});

describe('предложение установить после первого маршрута', () => {
  it('нет маршрута — нет предложения', () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      installer: fakeInstaller('prompt'),
    });
    expect(screen.queryByText('Установить «GoPoint»')).not.toBeInTheDocument();
  });

  it('Android: «Установить» открывает окно браузера', async () => {
    const installer = fakeInstaller('prompt');
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, { trip: TRIP, installer });
    await screen.findByRole('region', { name: 'Маршрут' });
    const banner = screen.getByRole('region', { name: 'Установить «GoPoint»' });
    fireEvent.click(within(banner).getByRole('button', { name: 'Установить' }));
    expect(installer.promptMock).toHaveBeenCalledTimes(1);
  });

  it('iPhone: «Как установить» и «Не сейчас» запоминается', async () => {
    const store = createMemoryStore();
    const first = renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      trip: TRIP,
      installer: fakeInstaller('ios'),
      store,
    });
    const banner = await screen.findByRole('region', { name: 'Установить «GoPoint»' });
    expect(within(banner).getByRole('link', { name: 'Как установить' })).toHaveAttribute(
      'href',
      '#/install',
    );
    fireEvent.click(within(banner).getByRole('button', { name: 'Не сейчас' }));
    expect(screen.queryByRole('region', { name: 'Установить «GoPoint»' })).not.toBeInTheDocument();
    first.unmount();
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      trip: TRIP,
      installer: fakeInstaller('ios'),
      store,
    });
    await screen.findByRole('region', { name: 'Маршрут' });
    expect(screen.queryByText('Установить «GoPoint»')).not.toBeInTheDocument();
  });
});
