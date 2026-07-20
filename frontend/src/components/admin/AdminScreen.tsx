"use client";

/**
 * Администрирование системы: четыре вкладки референса.
 *
 * Активная вкладка живёт в адресе (`?tab=…`), чтобы ссылку на журнал действий
 * можно было переслать коллеге, а «назад» возвращал на предыдущую вкладку.
 * Адрес читается через `window.location` и `popstate`, а не через
 * `useSearchParams`: последний требует обёртки `<Suspense>`, и на этом проекте
 * связка уже приводила к бесконечной заглушке вместо экрана.
 *
 * Ни одна проверка прав здесь не является защитой — она является подсказкой.
 * Право решает сервер: вкладка «Критерии риска» показывает форму правки всем,
 * у кого она открылась, и честно сообщает об отказе, если сервер откажет.
 * Прятать разделы от пользователя бессмысленно вдвойне: они описаны в ТЗ,
 * и человек должен понимать, чего ему не хватает.
 */

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { readToken } from "@/lib/api/auth";
import {
  ADMIN_TABS,
  createUser,
  fetchAuditLog,
  fetchReference,
  fetchRiskModels,
  fetchUsers,
  isAdminTab,
  updateRiskModel,
  updateUser,
  type AdminTab,
  type AdminUser,
  type AuditPage,
  type ReferencePayload,
  type RiskModelInfo,
} from "@/lib/api/admin";
import { explain } from "@/lib/api/request";

const ROLE_INITIALS: Record<string, string> = {
  admin: "АД",
  analyst: "АН",
  manager: "РК",
  viewer: "ПР",
};

function formatMoment(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function readTabFromLocation(): AdminTab {
  if (typeof window === "undefined") return "users";
  const value = new URLSearchParams(window.location.search).get("tab") ?? "";
  return isAdminTab(value) ? value : "users";
}

/**
 * Подписка на смену вкладки в адресе.
 *
 * `popstate` браузер шлёт только при переходе назад-вперёд, но не при
 * `pushState`. Поэтому после программной смены адреса событие рассылается
 * вручную (см. `openTab`) — так у вкладки остаётся ровно один источник
 * истины: сам адрес.
 */
function subscribeToLocation(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

/** На сервере адреса нет, поэтому первая отрисовка всегда «Пользователи». */
function serverTab(): AdminTab {
  return "users";
}

export function AdminScreen() {
  const [token] = useState<string | null>(() => readToken());

  /*
    Вкладка не хранится состоянием, а читается из адреса подпиской: два
    источника истины — состояние и адрес — неизбежно разъезжаются при переходе
    «назад», и разъезжаются молча. `useSyncExternalStore` заодно снимает
    расхождение при гидратации: на сервере отдаётся заведомая вкладка по
    умолчанию, на клиенте — настоящая.
  */
  const tab = useSyncExternalStore(subscribeToLocation, readTabFromLocation, serverTab);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [reference, setReference] = useState<ReferencePayload | null>(null);
  const [models, setModels] = useState<RiskModelInfo[] | null>(null);
  const [auditPage, setAuditPage] = useState<AuditPage | null>(null);

  const [showUserForm, setShowUserForm] = useState(false);
  const [modelCode, setModelCode] = useState<string>("");
  const [auditFilters, setAuditFilters] = useState({
    userLogin: "",
    action: "",
    dateFrom: "",
    dateTo: "",
    page: 1,
  });

  const openTab = useCallback((next: AdminTab) => {
    setError(null);
    setNotice(null);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.pushState(null, "", url);
    // `pushState` события не порождает — рассылаем его сами, иначе подписка на
    // адрес не узнает о переключении вкладки.
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, []);

  const loadUsers = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setUsers(await fetchUsers(token, signal));
      } catch (cause) {
        if (!signal?.aborted) setError(explain(cause));
      }
    },
    [token],
  );

  const loadAudit = useCallback(
    async (signal?: AbortSignal) => {
      try {
        setAuditPage(
          await fetchAuditLog(
            token,
            {
              userLogin: auditFilters.userLogin || undefined,
              action: auditFilters.action || undefined,
              dateFrom: auditFilters.dateFrom || undefined,
              dateTo: auditFilters.dateTo || undefined,
              page: auditFilters.page,
              pageSize: 25,
            },
            signal,
          ),
        );
      } catch (cause) {
        if (!signal?.aborted) setError(explain(cause));
      }
    },
    [token, auditFilters],
  );

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        if (tab === "users") await loadUsers(controller.signal);
        if (tab === "reference") {
          setReference(await fetchReference(token, controller.signal));
        }
        if (tab === "risk") {
          const payload = await fetchRiskModels(token, controller.signal);
          setModels(payload);
          setModelCode((previous) => previous || payload[0]?.code || "");
        }
        if (tab === "audit") await loadAudit(controller.signal);
      } catch (cause) {
        if (!controller.signal.aborted) setError(explain(cause));
      }
    }

    void load();
    return () => controller.abort();
  }, [tab, token, loadUsers, loadAudit]);

  const model = useMemo(
    () => models?.find((item) => item.code === modelCode) ?? null,
    [models, modelCode],
  );

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: "Главная" }, { label: "Администрирование" }]}
        title="Администрирование системы"
        subtitle="Пользователи, справочники, критерии риска, журнал действий"
        actions={
          tab === "users" ? (
            <button
              type="button"
              onClick={() => setShowUserForm((value) => !value)}
              className="rounded-card bg-accent px-3 py-2 text-sm font-medium text-accent-fg"
            >
              + Добавить пользователя
            </button>
          ) : null
        }
      />

      <div role="tablist" aria-label="Разделы администрирования" className="mb-5 flex flex-wrap gap-1 border-b border-border-base">
        {ADMIN_TABS.map((item) => (
          <button
            key={item.code}
            type="button"
            role="tab"
            aria-selected={tab === item.code}
            onClick={() => openTab(item.code)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${
              tab === item.code
                ? "border-accent font-semibold text-accent"
                : "border-transparent text-text-muted hover:text-text"
            }`}
          >
            {item.title}
          </button>
        ))}
      </div>

      {error && (
        <div
          role="alert"
          className="mb-4 rounded-panel border border-risk-high-border bg-risk-high-bg p-4"
        >
          <p className="text-sm font-medium text-risk-high-text">Действие не выполнено</p>
          <p className="mt-1 text-sm text-text-muted">{error}</p>
        </div>
      )}
      {notice && (
        <div
          role="status"
          className="mb-4 rounded-panel border border-risk-low-border bg-risk-low-bg p-4 text-sm text-risk-low-text"
        >
          {notice}
        </div>
      )}

      {tab === "users" && (
        <section aria-label="Пользователи">
          {showUserForm && (
            <UserForm
              busy={busy}
              territories={reference?.territories ?? []}
              onCancel={() => setShowUserForm(false)}
              onSubmit={async (body) => {
                setBusy(true);
                setError(null);
                try {
                  const created = await createUser(token, body);
                  setNotice(`Учётная запись «${created.login}» создана.`);
                  setShowUserForm(false);
                  await loadUsers();
                } catch (cause) {
                  setError(explain(cause));
                } finally {
                  setBusy(false);
                }
              }}
            />
          )}

          <div className="overflow-x-auto rounded-panel border border-border-base bg-surface shadow-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-base text-left text-xs text-text-muted">
                  <th className="px-4 py-3 font-medium">Ф.И.О.</th>
                  <th className="px-4 py-3 font-medium">Логин</th>
                  <th className="px-4 py-3 font-medium">Роль</th>
                  <th className="px-4 py-3 font-medium">Территория</th>
                  <th className="px-4 py-3 font-medium">Последний вход</th>
                  <th className="px-4 py-3 font-medium">Статус</th>
                  <th className="px-4 py-3 font-medium">Действия</th>
                </tr>
              </thead>
              <tbody>
                {(users ?? []).map((user) => (
                  <tr key={user.id} className="border-b border-border-base last:border-0">
                    <td className="px-4 py-3 text-text">{user.full_name}</td>
                    <td className="px-4 py-3 font-mono text-xs text-text-muted">{user.login}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-2">
                        <span
                          aria-hidden="true"
                          className="flex size-6 items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent"
                        >
                          {ROLE_INITIALS[user.role] ?? "??"}
                        </span>
                        <span className="text-text">{user.role_title}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3 text-text-muted">{user.territory}</td>
                    <td className="px-4 py-3 font-mono text-xs text-text-muted">
                      {formatMoment(user.last_login_at)}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs ${
                          user.is_active
                            ? "border-risk-low-border bg-risk-low-bg text-risk-low-text"
                            : "border-risk-none-border bg-risk-none-bg text-risk-none-text"
                        }`}
                      >
                        {user.is_active ? "Активен" : "Неактивен"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={async () => {
                          setBusy(true);
                          setError(null);
                          try {
                            await updateUser(token, user.id, { is_active: !user.is_active });
                            await loadUsers();
                          } catch (cause) {
                            setError(explain(cause));
                          } finally {
                            setBusy(false);
                          }
                        }}
                        className="text-xs text-accent underline disabled:opacity-40"
                      >
                        {user.is_active ? "Заблокировать" : "Разблокировать"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {users !== null && users.length === 0 && (
              <p className="p-4 text-sm text-text-muted">Учётных записей нет.</p>
            )}
          </div>
        </section>
      )}

      {tab === "reference" && (
        <section aria-label="Справочники" className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-panel border border-border-base bg-surface p-5 shadow-card">
            <h2 className="text-sm font-semibold text-text">Территории</h2>
            <p className="mt-0.5 text-xs text-text-muted">
              Справочник административно-территориального деления.
            </p>
            <div className="mt-3 max-h-96 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-text-muted">
                    <th className="px-2 py-1 font-medium">Код</th>
                    <th className="px-2 py-1 font-medium">Название</th>
                    <th className="px-2 py-1 font-medium">Қазақша</th>
                    <th className="px-2 py-1 font-medium">Уровень</th>
                  </tr>
                </thead>
                <tbody>
                  {(reference?.territories ?? []).map((row) => (
                    <tr key={row.id} className="border-t border-border-base">
                      <td className="px-2 py-1 font-mono text-text-muted">{row.code}</td>
                      <td className="px-2 py-1 text-text">{row.name_ru}</td>
                      <td className="px-2 py-1 text-text-muted">{row.name_kk ?? "—"}</td>
                      <td className="px-2 py-1 text-text-muted">{row.level}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-panel border border-border-base bg-surface p-5 shadow-card">
            <h2 className="text-sm font-semibold text-text">Роли и права</h2>
            <p className="mt-0.5 text-xs text-text-muted">
              Состав прав роли хранится в базе — его меняет администратор, а не релиз.
            </p>
            <ul className="mt-3 space-y-3">
              {(reference?.roles ?? []).map((role) => (
                <li key={role.code} className="rounded-card border border-border-base p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-text">{role.title}</span>
                    <span className="text-xs text-text-muted">
                      учётных записей: {role.users_count}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-text-muted">{role.description}</p>
                  <p className="mt-1 text-xs text-text-subtle">
                    Персональные данные:{" "}
                    {reference?.sensitive_access_levels.find(
                      (level) => level.code === role.sensitive_data_access,
                    )?.title ?? role.sensitive_data_access}
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-1">
                    {role.permissions.map((permission) => (
                      <li
                        key={permission.code}
                        title={permission.description}
                        className="rounded border border-border-base px-1.5 py-0.5 text-[10px] text-text-muted"
                      >
                        {permission.title}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {tab === "risk" && (
        <section aria-label="Критерии риска" className="space-y-5">
          <div className="rounded-panel border border-border-base bg-surface p-5 shadow-card">
            <label htmlFor="risk-model" className="text-xs font-semibold tracking-wide text-text-muted">
              МОДЕЛЬ РИСКА
            </label>
            <select
              id="risk-model"
              value={modelCode}
              onChange={(event) => setModelCode(event.target.value)}
              className="mt-2 w-full rounded-card border border-border-base bg-surface px-2 py-1.5 text-sm sm:w-96"
            >
              {(models ?? []).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.code} — {item.title}
                </option>
              ))}
            </select>

            {model && (
              <>
                <p className="mt-3 text-xs text-text-muted">
                  Действующая версия: <strong className="text-text">{model.version}</strong>{" "}
                  (исходная в коде — {model.base_version}). Версия записывается в каждую
                  оценку, поэтому прошлые оценки остаются воспроизводимыми и правкой весов
                  не переписываются.
                </p>

                <div className="mt-4 grid gap-5 lg:grid-cols-2">
                  <div>
                    <h3 className="text-xs font-semibold tracking-wide text-text-muted">
                      ИНДИКАТОРЫ И ВЕСА
                    </h3>
                    <table className="mt-2 w-full text-xs">
                      <thead>
                        <tr className="text-left text-text-muted">
                          <th className="px-2 py-1 font-medium">Код</th>
                          <th className="px-2 py-1 font-medium">Индикатор</th>
                          <th className="px-2 py-1 font-medium">Вес</th>
                        </tr>
                      </thead>
                      <tbody>
                        {model.indicators.map((indicator) => (
                          <tr key={indicator.code} className="border-t border-border-base">
                            <td className="px-2 py-1 font-mono text-text-muted">
                              {indicator.code}
                            </td>
                            <td className="px-2 py-1 text-text">{indicator.name}</td>
                            <td className="px-2 py-1 tabular-nums text-text">
                              {indicator.weight}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div>
                    <h3 className="text-xs font-semibold tracking-wide text-text-muted">
                      ПОРОГИ УРОВНЕЙ
                    </h3>
                    <table className="mt-2 w-full text-xs">
                      <thead>
                        <tr className="text-left text-text-muted">
                          <th className="px-2 py-1 font-medium">Балл от</th>
                          <th className="px-2 py-1 font-medium">Уровень</th>
                        </tr>
                      </thead>
                      <tbody>
                        {model.thresholds.map((threshold) => (
                          <tr key={threshold.level} className="border-t border-border-base">
                            <td className="px-2 py-1 tabular-nums text-text">
                              {threshold.from_score}
                            </td>
                            <td className="px-2 py-1 text-text">{threshold.title}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>

          {model && (
            <RiskModelForm
              key={model.code}
              busy={busy}
              model={model}
              onSubmit={async (body) => {
                setBusy(true);
                setError(null);
                try {
                  await updateRiskModel(token, model.code, body);
                  setNotice(
                    `Редакция ${body.version} записана и занесена в журнал действий. ` +
                      "Прошлые оценки не изменены.",
                  );
                  setModels(await fetchRiskModels(token));
                } catch (cause) {
                  setError(explain(cause));
                } finally {
                  setBusy(false);
                }
              }}
            />
          )}

          {model && model.history.length > 0 && (
            <div className="rounded-panel border border-border-base bg-surface p-5 shadow-card">
              <h3 className="text-sm font-semibold text-text">История редакций</h3>
              <ul className="mt-3 space-y-2">
                {model.history.map((entry, index) => (
                  <li key={index} className="rounded-card border border-border-base p-3 text-xs">
                    <p className="text-text">
                      Версия <strong>{entry.version}</strong> (на основе {entry.based_on ?? "—"})
                    </p>
                    <p className="mt-0.5 text-text-muted">
                      {entry.changed_by ?? "неизвестно"} · {formatMoment(entry.changed_at)}
                    </p>
                    {entry.comment && (
                      <p className="mt-0.5 text-text-subtle">{entry.comment}</p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {tab === "audit" && (
        <section aria-label="Журнал действий">
          <div className="rounded-panel border border-border-base bg-surface p-4 shadow-card">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label htmlFor="audit-login" className="text-xs text-text-muted">
                  Пользователь
                </label>
                <input
                  id="audit-login"
                  value={auditFilters.userLogin}
                  onChange={(event) =>
                    setAuditFilters((previous) => ({
                      ...previous,
                      userLogin: event.target.value,
                      page: 1,
                    }))
                  }
                  className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label htmlFor="audit-action" className="text-xs text-text-muted">
                  Действие
                </label>
                <select
                  id="audit-action"
                  value={auditFilters.action}
                  onChange={(event) =>
                    setAuditFilters((previous) => ({
                      ...previous,
                      action: event.target.value,
                      page: 1,
                    }))
                  }
                  className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
                >
                  <option value="">Все действия</option>
                  {(auditPage?.actions ?? []).map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="audit-from" className="text-xs text-text-muted">
                  Период с
                </label>
                <input
                  id="audit-from"
                  type="date"
                  value={auditFilters.dateFrom}
                  onChange={(event) =>
                    setAuditFilters((previous) => ({
                      ...previous,
                      dateFrom: event.target.value,
                      page: 1,
                    }))
                  }
                  className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
                />
              </div>
              <div>
                <label htmlFor="audit-to" className="text-xs text-text-muted">
                  Период по
                </label>
                <input
                  id="audit-to"
                  type="date"
                  value={auditFilters.dateTo}
                  onChange={(event) =>
                    setAuditFilters((previous) => ({
                      ...previous,
                      dateTo: event.target.value,
                      page: 1,
                    }))
                  }
                  className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
                />
              </div>
            </div>
            <p className="mt-3 text-xs text-text-subtle">
              Журнал доступен только на чтение. Изменить или удалить запись не может никто —
              журнал, который можно отредактировать, не является доказательством.
            </p>
          </div>

          <div className="mt-4 overflow-x-auto rounded-panel border border-border-base bg-surface shadow-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-base text-left text-xs text-text-muted">
                  <th className="px-4 py-3 font-medium">Время</th>
                  <th className="px-4 py-3 font-medium">Пользователь</th>
                  <th className="px-4 py-3 font-medium">Действие</th>
                  <th className="px-4 py-3 font-medium">Объект</th>
                  <th className="px-4 py-3 font-medium">IP</th>
                </tr>
              </thead>
              <tbody>
                {(auditPage?.items ?? []).map((entry) => (
                  <tr key={entry.id} className="border-b border-border-base last:border-0">
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-text-muted">
                      {formatMoment(entry.occurred_at)}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-text">
                      {entry.user_login ?? "—"}
                    </td>
                    <td className="px-4 py-2 text-text">{entry.action_title}</td>
                    <td className="px-4 py-2 text-xs text-text-muted">
                      {entry.entity_type ?? "—"}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-text-muted">
                      {entry.ip_address ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {auditPage !== null && auditPage.items.length === 0 && (
              <p className="p-4 text-sm text-text-muted">
                Записей за выбранный период нет.
              </p>
            )}
          </div>

          {auditPage && (
            <div className="mt-3 flex items-center gap-3 text-sm">
              <button
                type="button"
                disabled={auditPage.page <= 1}
                onClick={() =>
                  setAuditFilters((previous) => ({ ...previous, page: previous.page - 1 }))
                }
                className="rounded-card border border-border-base px-3 py-1 disabled:opacity-40"
              >
                Назад
              </button>
              <span className="text-text-muted">
                Страница {auditPage.page} · всего записей{" "}
                {auditPage.total.toLocaleString("ru-RU")}
              </span>
              <button
                type="button"
                disabled={auditPage.page * auditPage.page_size >= auditPage.total}
                onClick={() =>
                  setAuditFilters((previous) => ({ ...previous, page: previous.page + 1 }))
                }
                className="rounded-card border border-border-base px-3 py-1 disabled:opacity-40"
              >
                Вперёд
              </button>
            </div>
          )}
        </section>
      )}
    </>
  );
}

interface UserFormProps {
  busy: boolean;
  territories: ReferencePayload["territories"];
  onCancel: () => void;
  onSubmit: (body: {
    login: string;
    full_name: string;
    password: string;
    role_code: string;
    territory_id?: string | null;
  }) => void | Promise<void>;
}

/**
 * Форма новой учётной записи.
 *
 * Пароль вводится один раз и уходит на сервер; на клиенте он нигде не
 * сохраняется — ни в состоянии после отправки, ни в адресе, ни в журнале.
 */
function UserForm({ busy, territories, onCancel, onSubmit }: UserFormProps) {
  const [login, setLogin] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [roleCode, setRoleCode] = useState("viewer");
  const [territoryId, setTerritoryId] = useState("");

  return (
    <form
      aria-label="Новая учётная запись"
      className="mb-5 rounded-panel border border-border-base bg-surface p-5 shadow-card"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit({
          login: login.trim(),
          full_name: fullName.trim(),
          password,
          role_code: roleCode,
          territory_id: territoryId || null,
        });
        setPassword("");
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <label htmlFor="new-full-name" className="text-xs text-text-muted">
            Ф.И.О.
          </label>
          <input
            id="new-full-name"
            required
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label htmlFor="new-login" className="text-xs text-text-muted">
            Логин
          </label>
          <input
            id="new-login"
            required
            value={login}
            onChange={(event) => setLogin(event.target.value)}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label htmlFor="new-password" className="text-xs text-text-muted">
            Пароль
          </label>
          <input
            id="new-password"
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label htmlFor="new-role" className="text-xs text-text-muted">
            Роль
          </label>
          <select
            id="new-role"
            value={roleCode}
            onChange={(event) => setRoleCode(event.target.value)}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          >
            <option value="admin">Администратор</option>
            <option value="analyst">Аналитик</option>
            <option value="manager">Руководитель</option>
            <option value="viewer">Просмотр</option>
          </select>
        </div>
        <div>
          <label htmlFor="new-territory" className="text-xs text-text-muted">
            Территория
          </label>
          <select
            id="new-territory"
            value={territoryId}
            onChange={(event) => setTerritoryId(event.target.value)}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          >
            {/* Пустое значение означает доступ ко всем территориям, и это
                написано словами: пустая строка читалась бы как «не выбрано». */}
            <option value="">Все районы</option>
            {territories.map((territory) => (
              <option key={territory.id} value={territory.id}>
                {territory.name_ru}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
        >
          Создать
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-card border border-border-base px-4 py-2 text-sm text-text"
        >
          Отмена
        </button>
      </div>
    </form>
  );
}

interface RiskModelFormProps {
  busy: boolean;
  model: RiskModelInfo;
  onSubmit: (body: {
    version: string;
    weights: Array<{ code: string; weight: number }>;
    thresholds: Array<{ from_score: number; level: string }>;
    comment: string;
  }) => void | Promise<void>;
}

/**
 * Форма новой редакции модели риска.
 *
 * Номер версии обязателен и не подставляется автоматически: он попадает в
 * каждую последующую оценку и в журнал, и выбор человека здесь честнее
 * автоинкремента, который никому ничего не объясняет.
 */
function RiskModelForm({ busy, model, onSubmit }: RiskModelFormProps) {
  const [version, setVersion] = useState("");
  const [comment, setComment] = useState("");
  /*
    Веса берутся из действующей модели один раз при монтировании. Сброс формы
    при смене модели обеспечен ключом `key={model.code}` на месте вызова:
    перемонтирование честнее эффекта, который сбрасывает поля уже после того,
    как пользователь увидел чужие значения.
  */
  const [weights, setWeights] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      model.indicators.map((indicator) => [indicator.code, String(indicator.weight)]),
    ),
  );

  return (
    <form
      aria-label="Новая редакция модели риска"
      className="rounded-panel border border-border-base bg-surface p-5 shadow-card"
      onSubmit={(event) => {
        event.preventDefault();
        void onSubmit({
          version: version.trim(),
          comment: comment.trim(),
          weights: model.indicators.map((indicator) => ({
            code: indicator.code,
            weight: Number(weights[indicator.code] ?? indicator.weight),
          })),
          thresholds: model.thresholds.map((threshold) => ({
            from_score: threshold.from_score,
            level: threshold.level,
          })),
        });
      }}
    >
      <h3 className="text-sm font-semibold text-text">Изменить веса и пороги</h3>
      <p className="mt-0.5 text-xs text-text-muted">
        Доступно только администратору. Изменение журналируется отдельным действием и
        получает собственную версию; уже посчитанные оценки не пересчитываются.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="model-version" className="text-xs text-text-muted">
            Номер новой версии
          </label>
          <input
            id="model-version"
            required
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder={`отличный от ${model.version}`}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label htmlFor="model-comment" className="text-xs text-text-muted">
            Основание изменения
          </label>
          <input
            id="model-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
          />
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {model.indicators.map((indicator) => (
          <div key={indicator.code}>
            <label
              htmlFor={`weight-${indicator.code}`}
              className="text-xs text-text-muted"
              title={indicator.name}
            >
              {indicator.code}
            </label>
            <input
              id={`weight-${indicator.code}`}
              type="number"
              min={0}
              step="0.01"
              value={weights[indicator.code] ?? ""}
              onChange={(event) =>
                setWeights((previous) => ({
                  ...previous,
                  [indicator.code]: event.target.value,
                }))
              }
              className="mt-1 w-full rounded-card border border-border-base bg-surface px-2 py-1 text-sm"
            />
          </div>
        ))}
      </div>

      <button
        type="submit"
        disabled={busy || !version.trim()}
        className="mt-4 rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
      >
        Сохранить редакцию
      </button>
    </form>
  );
}
