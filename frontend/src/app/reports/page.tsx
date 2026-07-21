import { AppShell } from "@/components/layout/AppShell";
import { ReportsScreen } from "@/components/reports/ReportsScreen";

export const metadata = { title: "Отчёты и экспорт — Карта рисков" };

/**
 * Экран «Отчёты и экспорт».
 *
 * Страница серверная, содержимое клиентское: каталог шаблонов и доступность
 * форматов зависят от развёртывания, а токен пользователя живёт в браузере.
 */
export default function Page() {
  return (
    <AppShell>
      <ReportsScreen />
    </AppShell>
  );
}
