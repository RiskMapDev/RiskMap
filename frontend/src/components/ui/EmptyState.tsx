import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

/**
 * Пустое состояние.
 *
 * Отдельный компонент, потому что «данных нет» и «данные ещё грузятся» —
 * разные сообщения, и путать их нельзя. Показать ноль до окончания загрузки
 * значит соврать пользователю, а по ТЗ ложный ноль недопустим.
 */
export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-panel border border-dashed border-border-strong bg-surface-muted px-6 py-12 text-center">
      {Icon && <Icon className="size-8 text-text-subtle" aria-hidden="true" />}
      <p className="text-sm font-medium text-text">{title}</p>
      {description && <p className="max-w-md text-sm text-text-muted">{description}</p>}
      {action}
    </div>
  );
}
