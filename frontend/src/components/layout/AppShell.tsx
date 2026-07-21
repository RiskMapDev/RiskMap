import { AuthGuard } from "@/components/layout/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { Topbar } from "@/components/layout/Topbar";

interface AppShellProps {
  children: React.ReactNode;
  /** Действия в верхней панели, специфичные для экрана. */
  actions?: React.ReactNode;
  /**
   * Убрать внутренние отступы и прокрутку у области содержимого.
   * Нужно карте: она занимает всю площадь и управляет прокруткой сама.
   */
  bleed?: boolean;
}

/**
 * Оболочка приложения: сайдбар слева, верхняя панель, область содержимого.
 *
 * Сайдбар тёмный в обеих темах — он остаётся якорем интерфейса при
 * переключении светлых аналитических экранов и тёмной карты.
 */
export function AppShell({ children, actions, bleed = false }: AppShellProps) {
  return (
    /*
      Проверка сессии обёрнута вокруг всей оболочки, а не вставлена в каждый
      экран: пропустить её на одном экране слишком легко, и именно там
      пользователь и увидел бы пустое меню с подписью «Гость».
    */
    <AuthGuard>
    <div className="flex h-dvh overflow-hidden">
      {/*
        Сайдбар скрыт на узких экранах: по ТЗ на мобильном основной режим —
        список, а навигация уезжает в выдвижную панель.
      */}
      <div className="hidden md:block">
        <Sidebar />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar actions={actions} />
        <main
          id="main"
          className={
            bleed
              ? "relative min-h-0 flex-1 overflow-hidden"
              : "min-h-0 flex-1 overflow-y-auto p-6"
          }
        >
          {children}
        </main>
      </div>
    </div>
    </AuthGuard>
  );
}
