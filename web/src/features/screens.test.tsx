import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { createMemoryStore } from '../adapters/storage/localStore';
import { GeolocationError } from '../ports/Geolocation';
import { ApiError } from '../ports/LiveApi';
import { fakeApi, fakeInstaller, linesList, renderApp } from '../test-utils';
import { LiveRouteScreen } from './live-route/LiveRouteScreen';
import { LiveRoutesScreen } from './live-routes/LiveRoutesScreen';
import { LiveStopScreen } from './live-stop/LiveStopScreen';
import { SettingsScreen } from './settings/SettingsScreen';
import { MapScreen } from './start/MapScreen';

afterEach(() => {
  window.location.hash = '';
});

// Кнопка «Моё местоположение» одна: значок на карте (решение владельца).
function locateButton(): HTMLElement {
  return screen.getByRole('button', { name: 'Моё местоположение' });
}

describe('Настройки', () => {
  it('объясняет, как отличить на карте низкопольную машину от обычной', () => {
    renderApp(<SettingsScreen />);
    const legend = screen.getByRole('region', { name: 'Как отличить на карте' });
    expect(legend).toHaveTextContent('закрашенный номер: низкий пол');
    expect(legend).toHaveTextContent('номер в рамке: не низкий пол или не указан');
  });

  it('«Низкопольный транспорт» по умолчанию включена и читается как переключатель', () => {
    renderApp(<SettingsScreen />);
    const toggle = screen.getByRole('switch', { name: 'Низкопольный транспорт' });
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(toggle).toHaveAccessibleDescription(/Включено: маршруты и карта/);
  });

  it('выбор запоминается на устройстве', () => {
    const store = createMemoryStore();
    const first = renderApp(<SettingsScreen />, { store });
    fireEvent.click(screen.getByRole('switch'));
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
    expect(store.get('gopoint.lowFloorOnly')).toBe('false');
    first.unmount();
    renderApp(<SettingsScreen />, { store });
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('нажатие на подпись тоже переключает настройку', () => {
    renderApp(<SettingsScreen />);
    fireEvent.click(screen.getByText('Низкопольный транспорт'));
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('испорченное значение в памяти: настройка включена', () => {
    renderApp(<SettingsScreen />, { store: createMemoryStore({ 'gopoint.lowFloorOnly': '??' }) });
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });
});

describe('Главный экран', () => {
  it('показывает число низкопольных машин и машины на карте', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />);
    expect(await screen.findByText('На линии сейчас: 1 низкопольная машина')).toBeInTheDocument();
    const map = screen.getByRole('region', { name: /Карта Новосибирска/ });
    expect(within(map).getAllByRole('button')).toHaveLength(1);
  });

  it('при выключенной настройке все машины с пометками', async () => {
    const store = createMemoryStore({ 'gopoint.lowFloorOnly': 'false' });
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, { store });
    expect(await screen.findByText('На линии сейчас: 3 машины')).toBeInTheDocument();
    const map = screen.getByRole('region', { name: /Карта Новосибирска/ });
    expect(within(map).getByText(/Автобус 3, не низкий пол/)).toBeInTheDocument();
    expect(within(map).getByText(/Трамвай 13, низкий пол не указан/)).toBeInTheDocument();
  });

  it('нет низкопольных: серый блок и ссылка на настройки', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      api: fakeApi({ getVehicles: () => Promise.resolve([]) }),
    });
    expect(await screen.findByText('Транспорта сейчас нет')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Показать любой транспорт' })).toHaveAttribute(
      'href',
      '#/settings',
    );
  });

  it('нет сети: понятное сообщение и «Повторить»', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      api: fakeApi({
        getVehicles: () =>
          Promise.reject(new ApiError(0, 'NETWORK', 'Нет подключения к интернету.')),
      }),
    });
    // Перед ошибкой сайт один раз повторяет запрос (около секунды).
    expect(
      await screen.findByText('Нет подключения к интернету', {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });

  it('ошибка сервера: его сообщение по-русски', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      api: fakeApi({
        getVehicles: () =>
          Promise.reject(
            new ApiError(503, 'TRANSIT_UNAVAILABLE', 'Не удалось получить данные о транспорте.'),
          ),
      }),
    });
    expect(
      await screen.findByText('Не удалось получить данные о транспорте.', {}, { timeout: 4000 }),
    ).toBeInTheDocument();
  });

  it('кнопка «Моё местоположение» одна', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />);
    await screen.findByText(/На линии сейчас/);
    expect(screen.getAllByRole('button', { name: 'Моё местоположение' })).toHaveLength(1);
  });

  it('нажатие на машину открывает её карточку', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />);
    fireEvent.click(await screen.findByRole('button', { name: /Автобус 3/ }));
    expect(window.location.hash).toBe('#/vehicle/bus-3-1');
  });

  it('карточка машины: куда едет, следующая остановка, низкий пол', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: 'bus-3-1' }} />);
    expect(await screen.findByRole('heading', { name: 'Автобус 3' })).toBeInTheDocument();
    expect(await screen.findByText('в сторону Северный')).toBeInTheDocument();
    expect(screen.getByText('Следующая остановка')).toBeInTheDocument();
    expect(screen.getAllByText('Северный').length).toBeGreaterThan(0);
    expect(screen.getByText('низкий пол')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Весь маршрут' })).toHaveAttribute(
      'href',
      '#/transport/bus-3',
    );
  });

  it('карточка машины: минуты до следующей остановки и дальше по маршруту', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: 'bus-3-1' }} />);
    const next = await screen.findByRole('link', { name: 'Цирк' });
    expect(next.parentElement).toHaveTextContent('Цирк · 2 мин');
    const further = screen.getByRole('region', { name: 'Дальше по маршруту' });
    expect(further).toHaveTextContent('Площадь Маркса');
    expect(further).toHaveTextContent('9 мин');
    expect(further).toHaveTextContent('≈ 20 мин');
  });

  it('карточка машины: названия остановок ведут на экран остановки', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: 'bus-3-1' }} />);
    expect(await screen.findByRole('link', { name: 'Цирк' })).toHaveAttribute('href', '#/stop/2');
    const further = screen.getByRole('region', { name: 'Дальше по маршруту' });
    expect(within(further).getByRole('link', { name: 'Площадь Маркса' })).toHaveAttribute(
      'href',
      '#/stop/3',
    );
  });

  it('минут нет (сервер не ответил): карточка показывает остановку по линии', async () => {
    const api = fakeApi({
      getVehicleDetails: () => Promise.reject(new ApiError(503, 'TRANSIT_UNAVAILABLE', 'нет')),
    });
    renderApp(<MapScreen route={{ name: 'map', vehicleId: 'bus-3-1' }} />, { api });
    expect(await screen.findByText('Следующая остановка')).toBeInTheDocument();
    expect(screen.queryByText(/мин$/)).not.toBeInTheDocument();
  });

  it('машины больше нет на линии: так и говорим', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: 'bus-3-777' }} />);
    expect(await screen.findByText('Сведений об этой машине сейчас нет.')).toBeInTheDocument();
  });

  it('отказ в геолокации не ломает экран', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      geolocator: { locate: () => Promise.reject(new GeolocationError('denied')) },
    });
    await screen.findByText(/На линии сейчас/);
    await act(async () => {
      fireEvent.click(locateButton());
      await Promise.resolve();
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа к местоположению');
    expect(screen.getByText(/На линии сейчас/)).toBeInTheDocument();
  });

  it('без HTTPS объясняем, почему местоположения нет', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      geolocator: { locate: () => Promise.reject(new GeolocationError('insecure')) },
    });
    fireEvent.click(locateButton());
    expect(await screen.findByRole('alert')).toHaveTextContent(/https/);
  });
});

describe('Транспорт сейчас', () => {
  it('при включённой настройке только маршруты с машинами', async () => {
    renderApp(<LiveRoutesScreen />);
    expect(await screen.findByText('Автобус 3')).toBeInTheDocument();
    expect(screen.getByText('на линии: 2 машины')).toBeInTheDocument();
    expect(screen.queryByText('Автобус 36')).not.toBeInTheDocument();
  });

  it('при выключенной видны и маршруты без машин, серой меткой', async () => {
    renderApp(<LiveRoutesScreen />, {
      store: createMemoryStore({ 'gopoint.lowFloorOnly': 'false' }),
    });
    expect(await screen.findByText('Автобус 36')).toBeInTheDocument();
    expect(screen.getByText('сейчас нет на линии')).toBeInTheDocument();
  });

  it('фильтр по виду и поиск по номеру', async () => {
    renderApp(<LiveRoutesScreen />);
    await screen.findByText('Автобус 3');
    fireEvent.click(screen.getByRole('button', { name: 'Трамваи' }));
    expect(screen.getByRole('button', { name: 'Трамваи' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText('Автобус 3')).not.toBeInTheDocument();
    expect(screen.getByText('Трамвай 13')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Номер маршрута'), { target: { value: '99' } });
    expect(screen.getByText('Такого маршрута нет на линии.')).toBeInTheDocument();
  });

  it('строка ведёт на экран маршрута', async () => {
    renderApp(<LiveRoutesScreen />);
    expect(await screen.findByRole('link', { name: /Автобус 3/ })).toHaveAttribute(
      'href',
      '#/transport/bus-3',
    );
  });
});

describe('Маршрут на линии', () => {
  it('остановки по порядку и машины перед своей следующей остановкой', async () => {
    renderApp(<LiveRouteScreen lineId="bus-3" />);
    const list = await screen.findByRole('list', { name: 'Остановки по порядку' });
    const items = within(list)
      .getAllByRole('listitem')
      .map((li) => li.textContent);
    expect(items).toEqual(['Вокзал', 'Цирк', '3едет к «Северный»', 'Северный', '3на конечной']);
    expect(screen.getByText('в сторону Северный')).toBeInTheDocument();
  });

  it('направления переключаются', async () => {
    renderApp(<LiveRouteScreen lineId="bus-3" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Обратное' }));
    expect(screen.getByText('в сторону Вокзал')).toBeInTheDocument();
    expect(screen.getByText('сейчас нет на линии')).toBeInTheDocument();
  });

  it('при выключенной настройке у машин пометки', async () => {
    renderApp(<LiveRouteScreen lineId="bus-3" />, {
      store: createMemoryStore({ 'gopoint.lowFloorOnly': 'false' }),
    });
    expect(await screen.findByText('не низкий пол')).toBeInTheDocument();
  });

  it('маршрута нет: сообщение сервера', async () => {
    renderApp(<LiveRouteScreen lineId="bus-нет" />, {
      api: fakeApi({
        getLine: () => Promise.reject(new ApiError(404, 'LINE_NOT_FOUND', 'Такого маршрута нет.')),
      }),
    });
    await waitFor(
      () => {
        expect(screen.getByText('Такого маршрута нет.')).toBeInTheDocument();
      },
      { timeout: 4000 },
    );
  });
});

describe('Остановка', () => {
  it('что подъезжает: номер, куда, минуты; только низкопольные при включённой настройке', async () => {
    renderApp(<LiveStopScreen stopId="2" />);
    expect(await screen.findByRole('heading', { name: 'Цирк' })).toBeInTheDocument();
    expect(screen.getByText('Автобус 3 → Северный')).toBeInTheDocument();
    expect(screen.getByText('4 мин')).toBeInTheDocument();
    expect(screen.getByText('в 2 остановках')).toBeInTheDocument();
    expect(screen.queryByText(/Трамвай 13/)).not.toBeInTheDocument();
  });

  it('при выключенной настройке любой транспорт с пометкой и «≈» для дальних', async () => {
    renderApp(<LiveStopScreen stopId="2" />, {
      store: createMemoryStore({ 'gopoint.lowFloorOnly': 'false' }),
    });
    expect(await screen.findByText('Трамвай 13 → Писарева')).toBeInTheDocument();
    expect(screen.getByText('≈ 12 мин')).toBeInTheDocument();
    expect(screen.getByText('низкий пол не указан')).toBeInTheDocument();
  });

  it('никто не подъезжает: серый блок и ссылка на настройки', async () => {
    const api = fakeApi({
      getStopArrivals: () =>
        Promise.resolve({
          stop: { id: '2', name: 'Цирк', point: { lat: 55, lon: 83 } },
          arrivals: [],
        }),
    });
    renderApp(<LiveStopScreen stopId="2" />, { api });
    expect(await screen.findByText('Транспорта сейчас нет')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Показать любой транспорт' })).toHaveAttribute(
      'href',
      '#/settings',
    );
  });

  it('«Проложить маршрут отсюда» ставит точку А и просит выбрать «Куда»', async () => {
    renderApp(<LiveStopScreen stopId="2" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Проложить маршрут отсюда' }));
    expect(window.location.hash).toBe('#/search/to');
  });

  it('если «Куда» уже выбрано, сразу на карту с маршрутом', async () => {
    renderApp(<LiveStopScreen stopId="2" />, {
      trip: { to: { label: 'Аура', point: { lat: 55.04, lon: 82.93 } } },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Проложить маршрут отсюда' }));
    expect(window.location.hash).toBe('#/');
  });

  it('остановки нет: сообщение сервера', async () => {
    const api = fakeApi({
      getStopArrivals: () =>
        Promise.reject(new ApiError(404, 'STOP_NOT_FOUND', 'Такой остановки нет.')),
    });
    renderApp(<LiveStopScreen stopId="zz" />, { api });
    // Один повтор запроса перед ошибкой.
    expect(
      await screen.findByText('Такой остановки нет.', undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
  });

  it('экран маршрута ведёт на остановку', async () => {
    renderApp(<LiveRouteScreen lineId="bus-3" />);
    expect(
      await screen.findByRole('link', { name: 'Остановка «Цирк»: что подъезжает' }),
    ).toHaveAttribute('href', '#/stop/2');
  });
});

describe('Без сети: сохранённый список маршрутов', () => {
  it('маршруты видны без числа машин и с пояснением', async () => {
    const old = new Date(Date.now() - 10 * 60_000).toISOString();
    renderApp(<LiveRoutesScreen />, {
      api: fakeApi({ getLines: () => Promise.resolve(linesList(old)) }),
    });
    expect(
      await screen.findByText(
        'Машины на линии сейчас не показываются. Маршруты и остановки доступны.',
      ),
    ).toBeInTheDocument();
    // При включённой настройке видны все маршруты: сколько машин, неизвестно.
    expect(screen.getByRole('link', { name: /Автобус 36/ })).toBeInTheDocument();
    expect(screen.queryByText(/на линии: /)).not.toBeInTheDocument();
    expect(screen.queryByText('Транспорта сейчас нет')).not.toBeInTheDocument();
  });
});

describe('Установка на экран телефона', () => {
  it('Android: пункт в «Настройках» открывает окно браузера', async () => {
    const installer = fakeInstaller('prompt');
    renderApp(<SettingsScreen />, { installer });
    fireEvent.click(screen.getByRole('button', { name: 'Установить на экран телефона' }));
    await waitFor(() => {
      expect(installer.promptMock).toHaveBeenCalledTimes(1);
    });
    // Установлено: пункт пропадает.
    await waitFor(() => {
      expect(
        screen.queryByRole('button', { name: 'Установить на экран телефона' }),
      ).not.toBeInTheDocument();
    });
  });

  it('iPhone: пункт ведёт к инструкции', () => {
    renderApp(<SettingsScreen />, { installer: fakeInstaller('ios') });
    expect(screen.getByRole('link', { name: 'Установить на экран телефона' })).toHaveAttribute(
      'href',
      '#/install',
    );
  });

  it('уже установлено или браузер не умеет: ничего не предлагаем', () => {
    renderApp(<SettingsScreen />, { installer: fakeInstaller('installed') });
    expect(screen.queryByText('Установить на экран телефона')).not.toBeInTheDocument();
  });
});
