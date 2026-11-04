// Поиск адреса, выбор точки на карте и карточка «Откуда/Куда».
import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextEndpoint } from '../../domain/places';
import { GeolocationError } from '../../ports/Geolocation';
import { ApiError } from '../../ports/LiveApi';
import { App } from '../../App';
import { PLACES, fakePlaces, renderApp } from '../../test-utils';
import { MapScreen } from '../start/MapScreen';
import { PickPanel } from './PickOnMap';

afterEach(() => {
  window.location.hash = '';
  vi.useRealTimers();
});

const AURA = PLACES[0];

function searchBox(): HTMLElement {
  return screen.getByRole('searchbox');
}

describe('карточка «Откуда/Куда»', () => {
  it('пустые поля подписаны и открывают поиск нужной точки', () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Куда' }));
    expect(window.location.hash).toBe('#/search/to');
    fireEvent.click(screen.getByRole('button', { name: 'Откуда' }));
    expect(window.location.hash).toBe('#/search/from');
  });

  it('выбранные точки видны в полях и на карте, их можно поменять местами', async () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, {
      trip: {
        from: { label: 'Аура', point: { lat: 55.04, lon: 82.92 } },
        to: { label: 'Цирк', point: { lat: 55.05, lon: 82.91 } },
      },
    });
    expect(screen.getByRole('button', { name: 'Откуда: Аура' })).toBeInTheDocument();
    expect(await screen.findByText('Точка Б: Цирк')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Поменять точки А и Б местами' }));
    expect(screen.getByRole('button', { name: 'Откуда: Цирк' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Куда: Аура' })).toBeInTheDocument();
    // Обе точки есть: сразу строится маршрут.
    expect(await screen.findByRole('region', { name: 'Маршрут' })).toBeInTheDocument();
  });

  it('«Выбрать на карте» сначала для точки Б, потом для А', () => {
    const p = { label: 'x', point: { lat: 55, lon: 83 } };
    expect(nextEndpoint(null, null)).toBe('to');
    expect(nextEndpoint(null, p)).toBe('from');
    expect(nextEndpoint(p, p)).toBe('to');
  });

  it('без карты (список) кнопки «Выбрать на карте» нет', () => {
    renderApp(<MapScreen route={{ name: 'map', vehicleId: null }} />, { mapCanPick: false });
    expect(screen.queryByRole('button', { name: 'Выбрать на карте' })).not.toBeInTheDocument();
  });
});

describe('поиск адреса', () => {
  it('ищет после паузы, один запрос на всю фразу', async () => {
    const search = vi.fn((q: string) =>
      Promise.resolve(PLACES.filter((p) => p.title.toLowerCase() === q)),
    );
    renderApp(<MapScreen route={{ name: 'search', end: 'to' }} />, {
      places: fakePlaces({ search }),
    });
    expect(searchBox()).toHaveFocus();
    expect(searchBox()).toHaveAccessibleName('Куда: адрес или место');
    fireEvent.change(searchBox(), { target: { value: 'а' } });
    fireEvent.change(searchBox(), { target: { value: 'ау' } });
    fireEvent.change(searchBox(), { target: { value: 'аур' } });
    fireEvent.change(searchBox(), { target: { value: 'аура' } });
    expect(await screen.findByRole('button', { name: /Аура/ })).toBeInTheDocument();
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith('аура', expect.anything());
    // Вид места подписан текстом, а не только цветом.
    expect(screen.getByText('место')).toBeInTheDocument();
  });

  it('меньше трёх букв: не ищет и подсказывает', async () => {
    const search = vi.fn(() => Promise.resolve(PLACES));
    renderApp(<MapScreen route={{ name: 'search', end: 'to' }} />, {
      places: fakePlaces({ search }),
    });
    fireEvent.change(searchBox(), { target: { value: ' ау ' } });
    expect(screen.getByText('Введите хотя бы 3 буквы.')).toBeInTheDocument();
    await act(() => new Promise((r) => setTimeout(r, 400)));
    expect(search).not.toHaveBeenCalled();
  });

  it('устаревший запрос отменяется', async () => {
    const signals: AbortSignal[] = [];
    const search = vi.fn((q: string, signal?: AbortSignal) => {
      if (signal) signals.push(signal);
      // Первый запрос «висит», второй отвечает сразу.
      return q === 'мег'
        ? new Promise<never>(() => undefined)
        : Promise.resolve(PLACES.slice(0, 1));
    });
    renderApp(<MapScreen route={{ name: 'search', end: 'to' }} />, {
      places: fakePlaces({ search }),
    });
    fireEvent.change(searchBox(), { target: { value: 'мег' } });
    await waitFor(() => {
      expect(search).toHaveBeenCalledTimes(1);
    });
    fireEvent.change(searchBox(), { target: { value: 'аура' } });
    expect(await screen.findByRole('button', { name: /Аура/ })).toBeInTheDocument();
    expect(signals[0]?.aborted).toBe(true);
  });

  it('выбор подсказки ставит точку и возвращает на карту', async () => {
    renderApp(<MapScreen route={{ name: 'search', end: 'to' }} />);
    fireEvent.change(searchBox(), { target: { value: 'аура' } });
    fireEvent.click(await screen.findByRole('button', { name: /Аура/ }));
    expect(window.location.hash).toBe('#/');
  });

  it('ничего не нашлось: серый блок и совет', async () => {
    renderApp(<MapScreen route={{ name: 'search', end: 'from' }} />, {
      places: fakePlaces({ search: vi.fn(() => Promise.resolve([])) }),
    });
    fireEvent.change(searchBox(), { target: { value: 'щзщзщз' } });
    expect(await screen.findByText('Ничего не нашлось')).toBeInTheDocument();
    expect(screen.getByText(/выберите точку на карте/)).toBeInTheDocument();
  });

  it('поиск недоступен: понятное сообщение и «Повторить»', async () => {
    const search = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(
          503,
          'GEOCODER_UNAVAILABLE',
          'Поиск адресов сейчас не работает. Выберите точку на карте.',
        ),
      )
      .mockResolvedValue([AURA]);
    renderApp(<MapScreen route={{ name: 'search', end: 'to' }} />, {
      places: fakePlaces({ search }),
    });
    fireEvent.change(searchBox(), { target: { value: 'аура' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Поиск адресов сейчас не работает');
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('button', { name: /Аура/ })).toBeInTheDocument();
  });

  it('кнопки карты под поиском недоступны читалке', () => {
    renderApp(<MapScreen route={{ name: 'search', end: 'to' }} />);
    expect(screen.queryByRole('region', { name: 'Точки маршрута' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Моё местоположение' })).toHaveLength(1);
  });

  it('«Моё местоположение» ставит точку А', async () => {
    renderApp(<MapScreen route={{ name: 'search', end: 'from' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Моё местоположение' }));
    await waitFor(() => {
      expect(window.location.hash).toBe('#/');
    });
  });

  it('отказ в геолокации не ломает сайт: сообщение на главном экране', async () => {
    window.location.hash = '#/search/from';
    renderApp(<App />, {
      geolocator: { locate: () => Promise.reject(new GeolocationError('denied')) },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Моё местоположение' }));
    expect(await screen.findByText('Нет доступа к местоположению')).toBeInTheDocument();
    expect(window.location.hash).toBe('#/');
  });
});

describe('выбор точки на карте', () => {
  it('показывает адрес у булавки и выбирает точку', async () => {
    renderApp(<PickPanel end="to" center={{ lat: 55.0287, lon: 82.9195 }} />);
    expect(screen.getByText('Адрес точки Б')).toBeInTheDocument();
    expect(await screen.findByText('Красный проспект, 25/1')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать эту точку' }));
    expect(window.location.hash).toBe('#/');
  });

  it('рядом ничего нет: «Точка на карте», выбрать можно', async () => {
    renderApp(<PickPanel end="from" center={{ lat: 55, lon: 83 }} />, {
      places: fakePlaces({ reverse: vi.fn(() => Promise.resolve(null)) }),
    });
    expect(await screen.findByText('Точка на карте')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать эту точку' })).toBeEnabled();
  });

  it('за пределами города выбрать нельзя', async () => {
    renderApp(<PickPanel end="to" center={{ lat: 55.19, lon: 83.19 }} />, {
      places: fakePlaces({
        reverse: vi.fn(() =>
          Promise.reject(new ApiError(422, 'OUTSIDE_CITY', 'Эта точка за пределами Новосибирска.')),
        ),
      }),
    });
    expect(await screen.findByText('Эта точка за пределами Новосибирска.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать эту точку' })).toBeDisabled();
  });

  it('адрес не нашёлся из-за сбоя: точку всё равно можно выбрать', async () => {
    renderApp(<PickPanel end="to" center={{ lat: 55, lon: 83 }} />, {
      places: fakePlaces({ reverse: vi.fn(() => Promise.reject(new Error('сеть'))) }),
    });
    expect(
      await screen.findByText('Адрес не нашёлся, но точку можно выбрать.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Выбрать эту точку' })).toBeEnabled();
  });
});
