interface Breadcrumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumbs?: readonly Breadcrumb[];
  actions?: React.ReactNode;
}

export function PageHeader({ title, subtitle, breadcrumbs, actions }: PageHeaderProps) {
  return (
    <div className="mb-6">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label="Хлебные крошки" className="mb-2">
          <ol className="flex flex-wrap items-center gap-1.5 text-xs text-text-muted">
            {breadcrumbs.map((crumb, index) => (
              <li key={crumb.label} className="flex items-center gap-1.5">
                {index > 0 && (
                  <span aria-hidden="true" className="text-text-subtle">
                    ›
                  </span>
                )}
                {crumb.href ? (
                  <a href={crumb.href} className="hover:text-accent">
                    {crumb.label}
                  </a>
                ) : (
                  <span>{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-text">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}
