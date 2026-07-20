import { AppShell } from "@/components/layout/AppShell";
import { MapScreen } from "@/components/map/MapScreen";

export const metadata = { title: "Карта — Карта рисков" };

export default function MapPage() {
  /*
    Ни `Suspense`, ни `connection()` здесь больше нет.

    Граница Suspense требовалась из-за `useSearchParams` в экране карты, и
    именно она подвешивала страницу: дерево отрисовывалось в скрытом
    контейнере, эффекты не запускались, запросы к API не уходили. Экран карты
    теперь читает адрес напрямую, границы ожидания не нужно, и страница
    остаётся статической — данные она всё равно получает запросом к API.
  */
  return (
    <AppShell bleed>
      <MapScreen />
    </AppShell>
  );
}
