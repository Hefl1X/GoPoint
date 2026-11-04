import { ru } from './shared/ru';

// Пока пустая страница: экраны появятся в следующих задачах (запрос 3).
export function App() {
  return (
    <main className="app">
      <h1>{ru.appName}</h1>
      <p>{ru.tagline}</p>
    </main>
  );
}
