import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, fetchMeta } from './client';

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
