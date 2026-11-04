import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Без глобальных функций vitest библиотека не убирает экран сама: убираем после каждого теста.
afterEach(() => {
  cleanup();
});
