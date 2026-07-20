import { AppShell } from "@/components/layout/AppShell";
import { ImportWizard } from "@/components/import/ImportWizard";

export const metadata = { title: "Импорт данных — Карта рисков" };

/**
 * Экран «Данные (импорт)».
 *
 * Страница серверная и пустая: весь мастер клиентский, потому что три его шага
 * связаны состоянием загруженного файла и происходят без навигации. Данные для
 * первого шага он запрашивает сам — их состав зависит от прав пользователя,
 * а токен живёт в браузере.
 */
export default function Page() {
  return (
    <AppShell>
      <ImportWizard />
    </AppShell>
  );
}
