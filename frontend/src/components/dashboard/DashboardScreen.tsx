"use client";

import { useEffect, useState } from "react";

import { KpiCard } from "@/components/dashboard/KpiCard";
import { RiskDonut } from "@/components/dashboard/RiskDonut";
import { PageHeader } from "@/components/layout/PageHeader";
import { readToken } from "@/lib/api/auth";
import { fetchDashboard, type DashboardPayload } from "@/lib/api/dashboard";

/** Скелетон вместо нулей: показать «0» до загрузки — соврать пользователю. */
function KpiSkeleton() {
  return (
    <div className="rounded-panel border border-border-base bg-surface p-4 shadow-card">
      <div className="h-3 w-24 animate-pulse rounded bg-surface-hover" />
      <div className="mt-3 h-7 w-32 animate-pulse rounded bg-surface-hover" />
      <div className="mt-2 h-3 w-20 animate-pulse rounded bg-surface-hover" />
    </div>
  );
}

export function DashboardScreen() {
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  /*
    Токен читается лениво при первом рендере, а не записывается состоянием в
    эффекте: запись состояния прямо в теле эффекта вызывает лишний каскад
    перерисовок. Расхождения при гидратации не будет — токен нигде не
    отрисовывается, он только уходит в заголовок запроса.
  */
  const [token] = useState<string | null>(() => readToken());

  useEffect(() => {
    const controller = new AbortController();

    fetchDashboard(token, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setData(payload);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        const message = cause instanceof Error ? cause.message : "не удалось загрузить панель";
        /*
          Код 401 — не сбой, а отсутствие или истечение сессии. Отправлять
          пользователя разбираться с «ошибкой сервера» в этом случае значит
          скрывать простую причину за пугающей формулировкой.
        */
        setError(
          message.includes("401")
            ? "Сессия не начата или истекла — войдите в систему заново."
            : message,
        );
      });

    return () => controller.abort();
  }, [token]);

  function openSelection(drillDown: Record<string, string>) {
    const params = new URLSearchParams(drillDown);
    params.set("view", "list");
    window.location.href = `/map?${params.toString()}`;
  }

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Главная" }, { label: "Аналитическая панель" }]}
        title="Аналитическая панель"
        subtitle={data ? data.freshness.note : "Алматинская область"}
      />

      {error && (
        <div
          role="alert"
          className="mb-6 rounded-panel border border-risk-high-border bg-risk-high-bg p-4"
        >
          <p className="text-sm font-medium text-risk-high-text">Панель не загрузилась</p>
          <p className="mt-1 text-sm text-text-muted">{error}</p>
          {/*
            Пояснение зависит от причины. Раньше оно было одно на все случаи и
            под сообщением «сессия не начата» утверждало «это сбой связи с
            сервером» — два противоречащих объяснения одной ошибки.
          */}
          {error.includes("Сессия") ? (
            <a
              href="/login"
              className="mt-2 inline-block text-xs font-medium text-accent underline"
            >
              Перейти ко входу
            </a>
          ) : (
            <p className="mt-1 text-xs text-text-subtle">
              Это сбой связи с сервером, а не отсутствие данных.
            </p>
          )}
        </div>
      )}

      <section aria-label="Ключевые показатели">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {data
            ? data.kpis.map((kpi) => (
                <KpiCard key={kpi.code} kpi={kpi} onOpen={openSelection} />
              ))
            : /* Восемь скелетонов — ровно столько карточек будет. */
              Array.from({ length: 8 }, (_, index) => <KpiSkeleton key={index} />)}
        </div>
      </section>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <section
          aria-label="Объекты по уровню риска"
          className="rounded-panel border border-border-base bg-surface p-5 shadow-card"
        >
          <h2 className="text-sm font-semibold text-text">Объекты по уровню риска</h2>
          <p className="mt-0.5 text-xs text-text-muted">
            {data ? `${data.risk_distribution.total.toLocaleString("ru-RU")} объектов всего` : "…"}
          </p>
          <div className="mt-4">
            {data ? (
              <RiskDonut
                counts={data.risk_distribution.counts}
                labels={data.risk_distribution.labels}
                total={data.risk_distribution.total}
              />
            ) : (
              <div className="h-36 animate-pulse rounded bg-surface-hover" />
            )}
          </div>
          {/*
            Пояснение о составе выборки обязательно: у пользователя,
            ограниченного территорией, число в диаграмме меньше, чем в
            карточках показателей, и без объяснения это выглядит ошибкой.
          */}
          {data && (
            <p className="mt-3 text-xs text-text-subtle">{data.risk_distribution.scope_note}</p>
          )}
        </section>

        <section
          aria-label="Динамика бюджетного риска"
          className="rounded-panel border border-border-base bg-surface p-5 shadow-card"
        >
          <h2 className="text-sm font-semibold text-text">Динамика бюджетного риска</h2>
          <p className="mt-0.5 text-xs text-text-muted">
            средний балл по месяцам, 20 регионов
          </p>
          {/*
            Помесячную разбивку содержит только слой 8.3. Рисовать по
            остальным слоям линию значило бы выдумывать периоды, которых в
            источниках нет, — об этом сказано прямо под графиком.
          */}
          {data ? (
            <>
              <ol className="mt-4 flex h-32 items-end gap-1">
                {data.budget_dynamics.map((point) => {
                  const height = point.avg_score ? Math.max(4, point.avg_score * 2.4) : 4;
                  return (
                    <li
                      key={point.period}
                      className="flex flex-1 flex-col items-center gap-1"
                      title={`${point.period}: средний балл ${point.avg_score?.toFixed(1) ?? "нет данных"}`}
                    >
                      <span
                        className="w-full rounded-t bg-accent"
                        style={{ height: `${height}px` }}
                      />
                      <span className="text-[10px] text-text-subtle">
                        {point.period.slice(0, 2)}
                      </span>
                    </li>
                  );
                })}
              </ol>
              <p className="mt-3 text-xs text-text-subtle">
                Помесячная разбивка есть только у бюджетного слоя. У закупок,
                субсидий, инфраструктуры и организаций периодов в источниках нет,
                поэтому их динамика не показывается.
              </p>
            </>
          ) : (
            <div className="mt-4 h-32 animate-pulse rounded bg-surface-hover" />
          )}
        </section>
      </div>

      {data && data.territory_ranking.length > 0 && (
        <section
          aria-label="Территории по числу высокорисковых объектов"
          className="mt-4 rounded-panel border border-border-base bg-surface p-5 shadow-card"
        >
          <h2 className="text-sm font-semibold text-text">
            Территории с высоким и критическим риском
          </h2>
          <p className="mt-0.5 text-xs text-text-muted">
            по получателям субсидий — единственному слою с районной разбивкой и
            измеренным уровнем у большинства объектов
          </p>
          <ol className="mt-3 space-y-1.5">
            {data.territory_ranking.map((row) => (
              <li key={row.code} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-text">{row.name}</span>
                <span className="tabular-nums text-text-muted">{row.risky_count}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </>
  );
}
