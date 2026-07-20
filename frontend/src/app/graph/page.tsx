import { AppShell } from "@/components/layout/AppShell";
import { GraphScreen } from "@/components/graph/GraphScreen";

export const metadata = { title: "Граф связей — Карта рисков" };

export default function GraphPage() {
  return (
    <AppShell>
      <GraphScreen />
    </AppShell>
  );
}
