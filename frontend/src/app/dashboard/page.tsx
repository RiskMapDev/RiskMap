import { BarChart3 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

export const metadata = { title: "Аналитическая панель — Карта рисков" };

export default function DashboardPage() {
  return (
    <AppShell>
      <PageHeader
        breadcrumbs={[{ label: "Главная" }, { label: "Аналитическая панель" }]}
        title="Аналитическая панель"
        subtitle="Алматинская область"
      />
      <EmptyState
        icon={BarChart3}
        title="Показатели пока не подключены"
        description={
          "Данные загружаются в базу импортёрами слоёв. Пока импорт не выполнен, " +
          "панель намеренно не показывает нулевые значения: ноль и отсутствие " +
          "данных — разные состояния."
        }
      />
    </AppShell>
  );
}
