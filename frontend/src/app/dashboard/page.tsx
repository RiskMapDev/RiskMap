import { AppShell } from "@/components/layout/AppShell";
import { DashboardScreen } from "@/components/dashboard/DashboardScreen";

export const metadata = { title: "Аналитическая панель — Карта рисков" };

export default function DashboardPage() {
  return (
    <AppShell>
      <DashboardScreen />
    </AppShell>
  );
}
