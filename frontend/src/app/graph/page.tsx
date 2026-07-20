import { Share2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

export const metadata = { title: "Граф связей — Карта рисков" };

export default function Page() {
  return (
    <AppShell>
      <PageHeader title="Граф связей" subtitle="Организации, лица, договоры и субсидии" />
      <EmptyState
        icon={Share2}
        title="Граф ещё не подключён"
        description="Связи строятся из тех же данных, что питают индикаторы риска, — после импорта."
      />
    </AppShell>
  );
}
