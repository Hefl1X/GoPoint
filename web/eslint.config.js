import js from '@eslint/js';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// Сторонние карты и сервисы можно импортировать только внутри src/adapters/.
const adapterOnlyPackages = [
  { group: ['maplibre-gl', 'maplibre-gl/*'], message: 'Карта только в src/adapters/.' },
  { group: ['openapi-fetch', 'axios', 'ky'], message: 'Сеть только в src/adapters/.' },
  {
    group: ['virtual:pwa-register', 'virtual:pwa-register/*', 'workbox-*'],
    message: 'Service worker и установка только в src/adapters/pwa.',
  },
  {
    group: ['**/adapters/**/schema'],
    message: 'Сгенерированные типы API только в src/adapters/api.',
  },
];

export default tseslint.config(
  {
    ignores: [
      'dist',
      'dev-dist',
      'coverage',
      'playwright-report',
      'test-results',
      'src/adapters/api/schema.d.ts',
    ],
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.strict.rules,
      '@typescript-eslint/no-explicit-any': 'error',
      'no-empty': ['error', { allowEmptyCatch: false }],
      'no-restricted-imports': ['error', { patterns: adapterOnlyPackages }],
      'no-restricted-globals': [
        'error',
        { name: 'localStorage', message: 'Память устройства только через src/adapters/.' },
        { name: 'fetch', message: 'Сеть только через src/adapters/.' },
      ],
    },
  },
  {
    // domain/ не знает ни про адаптеры, ни про React.
    files: ['src/domain/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            ...adapterOnlyPackages,
            {
              group: ['**/adapters/**', 'react', 'react-dom'],
              message: 'domain/ без адаптеров и React.',
            },
          ],
        },
      ],
    },
  },
  {
    // Экраны и общие части знают только порты; адаптеры подставляет main.tsx.
    files: ['src/features/**/*.{ts,tsx}', 'src/shared/**/*.{ts,tsx}', 'src/ports/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            ...adapterOnlyPackages,
            { group: ['**/adapters/**'], message: 'Только через порты (src/ports).' },
          ],
        },
      ],
    },
  },
  {
    files: ['src/adapters/**/*.{ts,tsx}'],
    rules: { 'no-restricted-imports': 'off', 'no-restricted-globals': 'off' },
  },
  {
    files: ['vite.config.ts', 'playwright.config.ts', 'e2e/**/*.ts'],
    languageOptions: { globals: globals.node },
    rules: { 'no-restricted-globals': 'off' },
  },
);
