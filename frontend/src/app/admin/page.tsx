import { AdminScreen } from "@/components/admin/AdminScreen";
import { AppShell } from "@/components/layout/AppShell";

export const metadata = { title: "Администрирование — Карта рисков" };

/**
 * Экран «Администрирование».
 *
 * Страница серверная, содержимое клиентское: активная вкладка хранится в
 * адресе и переключается без навигации, а данные вкладок зависят от прав
 * пользователя, чей токен живёт в браузере.
 */
export default function Page() {
  return (
    <AppShell>
      <AdminScreen />
    </AppShell>
  );
}
