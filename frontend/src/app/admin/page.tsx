import { Settings } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

export const metadata = { title: "Администрирование — Карта рисков" };

export default function Page() {
  return (
    <AppShell>
      <PageHeader title="Администрирование системы" subtitle="Пользователи, справочники, критерии риска, журнал действий" />
      <EmptyState
        icon={Settings}
        title="Разделы администрирования в разработке"
        description=""
      />
    </AppShell>
  );
}
