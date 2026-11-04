/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// В разработке запросы /api уходят на сервер (адрес берётся из окружения,
// в клиенте адрес сервера не зашит: сайт всегда ходит на тот же адрес, что и сам).
const apiTarget = process.env.GOPOINT_API_PROXY ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { '/api': apiTarget },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test-setup.ts'],
  },
});
