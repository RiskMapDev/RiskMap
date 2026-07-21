import { AppShell } from "@/components/layout/AppShell";
import { ObjectCard } from "@/components/objects/ObjectCard";

export const metadata = { title: "Карточка объекта — Карта рисков" };

/**
 * Карточка объекта.
 *
 * Страница серверная, содержимое клиентское. `params` здесь намеренно не
 * читается: доступ к нему — это ожидание промиса, то есть ещё одна граница
 * Suspense, а на этом проекте такая граница оборачивалась вечной заглушкой.
 * Тип и идентификатор клиентский компонент берёт из `window.location.pathname`
 * — тот же адрес, тот же результат, без ожидания.
 */
export default function Page() {
  return (
    <AppShell>
      <ObjectCard />
    </AppShell>
  );
}
