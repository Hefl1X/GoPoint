import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, fetchMeta, httpLiveApi } from './client';

const goodMeta = {
  appName: 'GoPoint',
  version: '0.1.0',
  cityBounds: { southWest: { lat: 54.8, lon: 82.7 }, northEast: { lat: 55.2, lon: 83.2 } },
  refreshIntervalS: 30,
  lowFloorOnlyDefault: true,
  staleSeconds: 300,
};

function mockFetch(impl: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(impl));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('клиент API', () => {
  it('отдаёт проверенный ответ', async () => {
    mockFetch(() => Promise.resolve(Response.json(goodMeta)));
    await expect(fetchMeta()).resolves.toEqual(goodMeta);
  });

  it('повреждённый ответ превращается в понятную ошибку', async () => {
    mockFetch(() => Promise.resolve(Response.json({ ...goodMeta, cityBounds: [54.8, 82.7] })));
    await expect(fetchMeta()).rejects.toMatchObject({ code: 'BAD_RESPONSE' });
  });

  it('ошибка сервера в едином формате передаётся с русским сообщением', async () => {
    mockFetch(() =>
      Promise.resolve(
        Response.json(
          { code: 'NOT_IMPLEMENTED', message: 'Эта функция ещё в разработке.' },
          { status: 501 },
        ),
      ),
    );
    const error: unknown = await fetchMeta().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 501, message: 'Эта функция ещё в разработке.' });
  });

  it('нет сети', async () => {
    mockFetch(() => Promise.reject(new TypeError('Failed to fetch')));
    await expect(fetchMeta()).rejects.toMatchObject({
      code: 'NETWORK',
      message: 'Нет подключения к интернету.',
    });
  });
});

describe('машины на линии', () => {
  const vehicle = {
    id: 'bus-3-1',
    lineId: 'bus-3',
    type: 'bus',
    number: '3',
    direction: 'A',
    point: { lat: 55.03, lon: 82.92 },
    azimuth: 90,
    speedKmh: 20,
    lowFloor: 'yes',
    positionObservedAt: '2026-11-04T05:27:31Z',
  };
  const diagnostics = { fetchedAt: '2026-11-04T05:28:00Z', complete: true };

  it('передаёт lowFloorOnly и не отдаёт служебное время отметки', async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(Response.json({ vehicles: [vehicle], diagnostics })),
    );
    vi.stubGlobal('fetch', fetchMock);
    const result = await httpLiveApi.getVehicles(false);
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/live/vehicles?lowFloorOnly=false');
    expect(result).toHaveLength(1);
    expect(result[0]).not.toHaveProperty('positionObservedAt');
    expect(result[0]?.lowFloor).toBe('yes');
  });

  it('неизвестное значение низкого пола делает ответ непонятным, а не «да»', async () => {
    mockFetch(() =>
      Promise.resolve(
        Response.json({ vehicles: [{ ...vehicle, lowFloor: 'maybe' }], diagnostics }),
      ),
    );
    await expect(httpLiveApi.getVehicles(true)).rejects.toMatchObject({ code: 'BAD_RESPONSE' });
  });

  it('координаты массивом не принимаются', async () => {
    mockFetch(() =>
      Promise.resolve(Response.json({ vehicles: [{ ...vehicle, point: [55, 82] }], diagnostics })),
    );
    await expect(httpLiveApi.getVehicles(true)).rejects.toMatchObject({ code: 'BAD_RESPONSE' });
  });

  it('id маршрута кодируется в адресе', async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(Response.json({}, { status: 404 })),
    );
    vi.stubGlobal('fetch', fetchMock);
    await httpLiveApi.getLine('minibus-30А', true).catch(() => undefined);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/v1/live/routes/minibus-30%D0%90?lowFloorOnly=true',
    );
  });
});
