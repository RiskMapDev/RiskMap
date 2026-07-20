"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Database,
  FileText,
  Map,
  Settings,
  Share2,
  type LucideIcon,
} from "lucide-react";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

/** Состав и порядок пунктов заданы ТЗ и подтверждены всеми UI-референсами. */
const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Дашборд", icon: BarChart3 },
  { href: "/map", label: "Карта", icon: Map },
  { href: "/import", label: "Данные (импорт)", icon: Database },
  { href: "/reports", label: "Отчёты", icon: FileText },
  { href: "/graph", label: "Граф связей", icon: Share2 },
  { href: "/admin", label: "Администрирование", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Основная навигация"
      className="flex h-full w-60 shrink-0 flex-col bg-sidebar-bg text-sidebar-fg"
    >
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span
          aria-hidden="true"
          className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg"
        >
          <Map className="size-4.5" strokeWidth={2.5} />
        </span>
        <span className="text-[15px] font-semibold text-white">Карта рисков</span>
      </div>

      <p className="px-5 pb-2 pt-3 text-[11px] font-medium uppercase tracking-wider text-sidebar-fg-muted">
        Навигация
      </p>

      <ul className="flex flex-1 flex-col gap-0.5 px-3">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          /*
            Точное совпадение либо вложенный маршрут: карточка объекта
            /objects/... должна подсвечивать тот раздел, из которого открыта,
            а не гасить подсветку целиком.
          */
          const isActive = pathname === href || pathname.startsWith(`${href}/`);

          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={isActive ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "bg-sidebar-active-bg font-medium text-sidebar-active-fg"
                    : "hover:bg-sidebar-hover-bg hover:text-white"
                }`}
              >
                <Icon className="size-4.5 shrink-0" aria-hidden="true" />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>

      <p className="px-5 py-4 text-[11px] text-sidebar-fg-muted">© 2026 Акимат</p>
    </nav>
  );
}
