import { Map } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

export const metadata = { title: "Карта рисков — Карта рисков" };

export default function Page() {
  return (
    <AppShell>
      <PageHeader title="Карта" subtitle="Алматинская область и районы" />
      <EmptyState
        icon={Map}
        title="Карта ещё не подключена"
        description="Границы выгружены из OpenStreetMap и лежат в data/boundaries, но слой карты подключается после загрузки данных в базу."
      />
    </AppShell>
  );
}
