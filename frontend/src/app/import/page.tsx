import { Database } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

export const metadata = { title: "Импорт данных — Карта рисков" };

export default function Page() {
  return (
    <AppShell>
      <PageHeader title="Загрузка и импорт данных" subtitle="Мастер загрузки в 3 шага" />
      <EmptyState
        icon={Database}
        title="Мастер импорта в разработке"
        description="Импортёры слоёв работают из командной строки; интерфейс мастера подключается следующим этапом."
      />
    </AppShell>
  );
}
