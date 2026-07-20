import { FileText } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

export const metadata = { title: "Отчёты и экспорт — Карта рисков" };

export default function Page() {
  return (
    <AppShell>
      <PageHeader title="Отчёты и экспорт" subtitle="Формирование аналитических справок и выгрузка данных" />
      <EmptyState
        icon={FileText}
        title="Шаблоны отчётов ещё не подключены"
        description="Восемь шаблонов по ТЗ появятся после подключения источников данных."
      />
    </AppShell>
  );
}
