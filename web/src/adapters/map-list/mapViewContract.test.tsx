// Общее описание порта MapView, которое проверяется на адаптере-списке.
// Адаптер MapLibre проверяется тем же сценарием в e2e (нужен настоящий WebGL).
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { MapView, MapViewProps } from '../../ports/MapView';
import { ListMapView } from './ListMapView';

function props(overrides: Partial<MapViewProps> = {}): MapViewProps {
  return {
    label: 'Карта Новосибирска',
    bounds: { southWest: { lat: 54.8, lon: 82.7 }, northEast: { lat: 55.2, lon: 83.2 } },
    vehicles: [
      {
        id: 'a',
        number: '3',
        type: 'bus',
        lowFloor: 'yes',
        point: { lat: 55, lon: 83 },
        muted: false,
      },
      {
        id: 'b',
        number: '13',
        type: 'tram',
        lowFloor: 'no',
        point: { lat: 55, lon: 83 },
        muted: true,
      },
    ],
    selectedVehicleId: null,
    routeLine: null,
    routeColor: '#1d4ed8',
    userLocation: null,
    focus: null,
    onVehicleSelect: vi.fn(),
    ...overrides,
  };
}

function contract(name: string, View: MapView) {
  describe(`порт MapView: ${name}`, () => {
    it('подписан для экранной читалки', () => {
      render(<View {...props()} />);
      expect(screen.getByRole('region', { name: 'Карта Новосибирска' })).toBeInTheDocument();
    });

    it('показывает каждую машину, низкий пол не только цветом', () => {
      render(<View {...props()} />);
      expect(screen.getByText(/Автобус 3, низкий пол/)).toBeInTheDocument();
      expect(screen.getByText(/Трамвай 13, не низкий пол/)).toBeInTheDocument();
    });

    it('выбор машины сообщает её id', () => {
      const onVehicleSelect = vi.fn();
      render(<View {...props({ onVehicleSelect })} />);
      fireEvent.click(screen.getByText(/Трамвай 13/));
      expect(onVehicleSelect).toHaveBeenCalledWith('b');
    });

    it('выбранная машина отмечена', () => {
      render(<View {...props({ selectedVehicleId: 'a' })} />);
      expect(screen.getByRole('button', { name: /Автобус 3/ })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
    });

    it('пустой список не ломает вид', () => {
      render(<View {...props({ vehicles: [] })} />);
      expect(screen.getByRole('region', { name: 'Карта Новосибирска' })).toBeInTheDocument();
    });
  });
}

contract('список вместо карты', ListMapView);
