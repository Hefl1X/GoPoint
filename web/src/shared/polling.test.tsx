// Положения машин обновляются по таймеру и не обновляются, пока вкладка скрыта.
import { focusManager } from '@tanstack/react-query';
import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MapScreen } from '../features/start/MapScreen';
import { META, VEHICLES, fakeApi, renderApp } from '../test-utils';

afterEach(() => {
  focusManager.setFocused(undefined);
});

const fastMeta = { ...META, refreshIntervalS: 1 };

function setup() {
  const getVehicles = vi.fn(() => Promise.resolve(VEHICLES));
  const api = fakeApi({ getMeta: () => Promise.resolve(fastMeta), getVehicles });
  renderApp(<MapScreen vehicleId={null} />, { api });
  return getVehicles;
}

describe('обновление положений', () => {
  it('идёт раз в интервал, пока вкладка видна', async () => {
    const getVehicles = setup();
    await screen.findByText(/На линии сейчас/);
    await waitFor(
      () => {
        expect(getVehicles.mock.calls.length).toBeGreaterThanOrEqual(3);
      },
      { timeout: 4000 },
    );
  });

  it('останавливается, когда вкладка скрыта', async () => {
    const getVehicles = setup();
    await screen.findByText(/На линии сейчас/);
    focusManager.setFocused(false);
    const before = getVehicles.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 2500));
    expect(getVehicles.mock.calls.length).toBe(before);
  });
});
