"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, Database, Info, MapPin } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { RiskBadge } from "@/components/risk/RiskBadge";
import { fetchObjectDetail, type FactorRow, type ObjectDetailResponse } from "@/lib/api/object-detail";
import { explain } from "@/lib/api/request";
import { OBJECT_TYPE_LABELS, type ObjectType } from "@/lib/query-spec";
import { RISK_LEVELS, riskMeta, type RiskLevel } from "@/lib/risk";
import { formatDate, formatShare } from "@/lib/format";

/**
 * Отсутствие значения пишется словами.
 *
 * Прочерк на карточке не годится: в списке он читается как «в этой ячейке
 * ничего», а здесь у каждой строки есть подпись, и рядом с ней прочерк
 * неотличим от опечатки. Ноль тем более: ноль в этой системе означает
 * измеренный ноль, и подменять им отсутствие измерения ТЗ запрещает.
 */
const NOT_FILLED = "не заполнено";
const NOT_MEASURED = "не измерено";

const NUMBER_FORMAT = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const ISO_DATETIME = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/;

/** Дата и время загрузки: «20.07.2026, 19:58». */
function formatDateTime(value: string): string {
  const match = ISO_DATETIME.exec(value);
  if (!match) return formatDate(value);
  return `${formatDate(match[1])}, ${match[2]}:${match[3]}`;
}

function isRiskLevel(value: string): value is RiskLevel {
  return (RISK_LEVELS as readonly string[]).includes(value);
}

/**
 * Пояснение с заглавной буквы.
 *
 * Причины приходят с сервера как продолжение фразы («район не указан в
 * источнике»), а на карточке становятся самостоятельным предложением после
 * точки. Строчная буква в начале читается как обрыв текста.
 */
function asSentence(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/**
 * Значение поля сведений в человекочитаемом виде.
 *
 * Логическое «нет» показывается словом, а не пустотой: пустая ячейка напротив
 * подписи «Расторгнут» читается как «неизвестно», хотя сервер ответил
 * определённо.
 */
function formatFieldValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return NOT_FILLED;
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  if (typeof value === "number") {
    return Number.isFinite(value) ? NUMBER_FORMAT.format(value) : NOT_FILLED;
  }
  if (typeof value === "string") {
    if (ISO_DATE.test(value)) return formatDate(value);
    if (ISO_DATETIME.test(value)) return formatDateTime(value);
    // Код уровня риска сам по себе нечитаем. Подпись поля уже говорит, что
    // это уровень, поэтому подставляется человеческое название.
    if (/уровень/i.test(key) && isRiskLevel(value)) return riskMeta(value).label;
    return value;
  }
  return String(value);
}

/** Число фактора: `null` означает «не вычислено», а не ноль. */
function formatFactorNumber(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return NOT_MEASURED;
  return NUMBER_FORMAT.format(value);
}

/** Подписи ключей происхождения записи. */
const PROVENANCE_LABELS: Record<string, string> = {
  source_layer: "Слой источника",
  source_row_ref: "Строка в источнике",
  natural_key: "Ключ записи в источнике",
  imported_at: "Дата загрузки",
  data_as_of: "Данные актуальны на",
};

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon?: typeof Info;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-panel border border-border-base bg-surface p-4">
      <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
        {Icon && <Icon className="size-3.5" aria-hidden="true" />}
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** Пары «подпись — значение» в две колонки. */
function DefinitionList({ rows }: { rows: Array<[string, string]> }) {
  if (rows.length === 0) {
    return <p className="text-sm text-text-subtle">Сведений по этому объекту источник не даёт.</p>;
  }

  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border-base pb-1.5">
          <dt className="text-xs text-text-muted">{label}</dt>
          <dd className="text-sm text-text">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function MeasuredFactors({ rows }: { rows: FactorRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-subtle">
        Ни один фактор модели не измерен. Балл получен без вклада факторов, и опираться на него
        нельзя — смотрите раздел «Не измерено».
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm">
        <caption className="sr-only">Измеренные факторы риска с весом, значением и вкладом</caption>
        <thead>
          <tr className="border-b border-border-strong text-left text-xs uppercase tracking-wider text-text-muted">
            <th scope="col" className="py-1.5 pr-3 font-medium">Код</th>
            <th scope="col" className="py-1.5 pr-3 font-medium">Фактор</th>
            <th scope="col" className="py-1.5 pr-3 text-right font-medium">Вес</th>
            <th scope="col" className="py-1.5 pr-3 text-right font-medium">Значение</th>
            <th scope="col" className="py-1.5 pr-3 text-right font-medium">Вклад</th>
            <th scope="col" className="py-1.5 font-medium">Влияние</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.code} className="border-b border-border-base align-top">
              <td className="py-2 pr-3 font-mono text-xs text-text-muted">{row.code}</td>
              <td className="py-2 pr-3 text-text">
                {row.name}
                {row.source && (
                  <span className="mt-0.5 block text-xs text-text-subtle">
                    Источник: {row.source}
                  </span>
                )}
                {row.note && (
                  <span className="mt-0.5 block text-xs text-text-subtle">{row.note}</span>
                )}
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums text-text">
                {formatFactorNumber(row.weight)}
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums text-text">
                {formatFactorNumber(row.value)}
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums text-text">
                {formatFactorNumber(row.contribution)}
              </td>
              {/*
                Влияние словами, а не знаком или цветом числа. «0» в колонке
                вклада можно прочитать и как «не повлиял», и как «не измерен»,
                а это разные вещи: первое — результат, второе — его отсутствие.
              */}
              <td className="py-2 text-text-muted">{row.effect}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UnmeasuredFactors({ rows }: { rows: FactorRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        Неизмеренных факторов нет: модель отработала на полных данных.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.code} className="border-b border-border-base pb-2 last:border-0 last:pb-0">
          <p className="text-sm text-text">
            <span className="font-mono text-xs text-text-muted">{row.code}</span> {row.name}
          </p>
          {/*
            Причина обязательна для каждого фактора: именно она объясняет
            низкую полноту и серый уровень. Строка без причины оставила бы
            пользователя с необъяснённым «нет данных».
          */}
          <p className="mt-0.5 text-xs text-text-subtle">
            Причина: {asSentence(row.note || "источник не сообщает, почему фактор не измерен")}
          </p>
          {row.source && (
            <p className="mt-0.5 text-xs text-text-subtle">Ожидаемый источник: {row.source}</p>
          )}
          <p className="mt-0.5 text-xs text-text-subtle">
            Вес в модели: {formatFactorNumber(row.weight)}
          </p>
        </li>
      ))}
    </ul>
  );
}

function CardSkeleton() {
  return (
    <div className="space-y-4" aria-hidden="true">
      <div className="h-24 animate-pulse rounded-panel bg-surface-hover" />
      <div className="h-40 animate-pulse rounded-panel bg-surface-hover" />
      <div className="h-56 animate-pulse rounded-panel bg-surface-hover" />
    </div>
  );
}

/** Адрес карточки: `/objects/{тип}/{идентификатор}`. */
export function parseCardPath(pathname: string): { type: string; id: string } | null {
  const match = /^\/objects\/([^/]+)\/([^/]+)\/?$/.exec(pathname);
  if (!match) return null;
  try {
    return { type: decodeURIComponent(match[1]), id: decodeURIComponent(match[2]) };
  } catch {
    return null;
  }
}

interface ObjectCardProps {
  /** Готовые данные — для тестов и предпросмотра. Без них карточка грузит сама. */
  detail?: ObjectDetailResponse;
}

/**
 * Карточка объекта с расшифровкой оценки риска.
 *
 * Балл без объяснения — число, которому остаётся либо верить на слово, либо не
 * верить, и для принятия решений не годится ни то ни другое. Поэтому
 * расшифровка здесь не дополнение, а основное содержимое карточки, а раздел
 * «Не измерено» показывается всегда — он и объясняет, почему полнота низкая.
 */
export function ObjectCard({ detail: preloaded }: ObjectCardProps = {}) {
  const [detail, setDetail] = useState<ObjectDetailResponse | null>(preloaded ?? null);
  const [state, setState] = useState<"loading" | "error" | "ready">(
    preloaded ? "ready" : "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const [route, setRoute] = useState<{ type: string; id: string } | null>(null);
  const [attempt, setAttempt] = useState(0);

  /*
    Адрес читается из `window.location`, а не через `useSearchParams` или
    `use(params)`. Оба заставляют ждать ближайшую границу Suspense, и на этом
    проекте ожидание не заканчивалось никогда: дерево отрисовывалось в скрытом
    контейнере, эффекты не запускались, запросы не уходили. Подробности — в
    комментарии `MapScreen`.
  */
  useEffect(() => {
    if (preloaded) return;
    const apply = () => setRoute(parseCardPath(window.location.pathname));
    apply();
    window.addEventListener("popstate", apply);
    return () => window.removeEventListener("popstate", apply);
  }, [preloaded]);

  useEffect(() => {
    if (preloaded || route === null) return;

    const controller = new AbortController();
    fetchObjectDetail(route.type, route.id, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setDetail(payload);
        setError(null);
        setState("ready");
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(explain(cause));
        setState("error");
      });

    return () => controller.abort();
  }, [preloaded, route, attempt]);

  const retry = useCallback(() => {
    setState("loading");
    setAttempt((value) => value + 1);
  }, []);

  if (state === "loading") {
    return (
      <>
        <PageHeader title="Карточка объекта" subtitle="Загружаю сведения…" />
        <CardSkeleton />
      </>
    );
  }

  if (state === "error" || detail === null) {
    return (
      <>
        <PageHeader title="Карточка объекта" />
        <div
          role="alert"
          className="rounded-panel border border-border-strong bg-surface-muted p-6 text-center"
        >
          <p className="text-sm font-medium text-text">Карточка не открылась</p>
          <p className="mt-1 text-sm text-text-muted">
            {error ?? "Адрес карточки не разобран: ожидается /objects/тип/идентификатор."}
          </p>
          <p className="mt-1 text-xs text-text-subtle">
            Отказ означает либо отсутствие объекта, либо ограничение доступа по территории. Это не
            признак того, что у объекта нет данных.
          </p>
          <div className="mt-3 flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={retry}
              className="rounded border border-border-base bg-surface px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
            >
              Повторить
            </button>
            <a
              href="/map?view=list"
              className="rounded border border-border-base bg-surface px-3 py-1.5 text-sm text-text hover:bg-surface-hover"
            >
              К списку объектов
            </a>
          </div>
        </div>
      </>
    );
  }

  const { risk, territory, factors } = detail;
  const typeLabel = OBJECT_TYPE_LABELS[detail.object_type as ObjectType] ?? detail.object_type;

  const fieldRows: Array<[string, string]> = Object.entries(detail.fields).map(([key, value]) => [
    key,
    formatFieldValue(key, value),
  ]);

  const provenanceRows: Array<[string, string]> = Object.entries(detail.provenance).map(
    ([key, value]) => [PROVENANCE_LABELS[key] ?? key, formatFieldValue(key, value)],
  );

  return (
    <>
      <PageHeader
        title={detail.title || detail.object_id}
        subtitle={`${typeLabel} · слой ${detail.source_layer} · ${detail.object_id}`}
        breadcrumbs={[
          { label: "Карта рисков", href: "/map" },
          { label: "Объекты", href: "/map?view=list" },
          { label: typeLabel },
        ]}
        actions={<RiskBadge level={risk.level} score={risk.score} preliminary={risk.is_preliminary} />}
      />

      <a
        href="/map?view=list"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-text-muted hover:text-accent"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        К списку объектов
      </a>

      <div className="space-y-4">
        {/*
          Предварительный балл вынесен отдельным предупреждением, а не подан
          рядом с окончательным. Показать их одинаково — значит выдать оценку
          на неполных данных за готовый вывод.
        */}
        {risk.is_preliminary && (
          <div
            role="note"
            className="flex items-start gap-2 rounded-panel border border-risk-none-border bg-risk-none-bg p-4"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-risk-none-text" aria-hidden="true" />
            <div>
              <p className="text-sm font-medium text-risk-none-text">
                Балл предварительный — это не окончательная оценка
              </p>
              <p className="mt-1 text-sm text-text-muted">
                Данных хватило не на все факторы модели, поэтому уровень остаётся «
                {riskMeta(risk.level).label}», а балл{" "}
                {risk.score === null ? "не рассчитан" : NUMBER_FORMAT.format(risk.score)} показан
                справочно и основанием для вывода не является. Чего именно не хватило — в разделе
                «Не измерено» ниже.
              </p>
            </div>
          </div>
        )}

        <Section title="Оценка риска" icon={Info}>
          <div className="flex flex-wrap items-center gap-3">
            <RiskBadge level={risk.level} score={risk.score} preliminary={risk.is_preliminary} />
            <span className="text-sm text-text-muted">
              Полнота данных:{" "}
              {risk.completeness === null ? "не рассчитывалась" : formatShare(risk.completeness)}
            </span>
          </div>

          <div className="mt-3">
            <DefinitionList
              rows={[
                [
                  "Балл",
                  risk.score === null
                    ? "не рассчитан"
                    : `${NUMBER_FORMAT.format(risk.score)}${
                        risk.is_preliminary ? " (предварительный)" : ""
                      }`,
                ],
                ["Модель", risk.model_code ?? "не указана"],
                ["Версия модели", risk.model_version ?? "не указана"],
              ]}
            />
          </div>

          {risk.override_reason && (
            <p className="mt-3 rounded border border-risk-critical-border bg-risk-critical-bg p-3 text-sm text-risk-critical-text">
              Сработало жёсткое правило: {risk.override_reason}
            </p>
          )}

          {risk.explanation && (
            <p className="mt-3 text-sm text-text-muted">{risk.explanation}</p>
          )}

          {risk.notes.length > 0 && (
            <ul className="mt-3 space-y-1">
              {risk.notes.map((note) => (
                <li key={note} className="text-sm text-text-subtle">
                  {note}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Измеренные факторы" icon={Info}>
          <MeasuredFactors rows={factors.measured} />
        </Section>

        {/*
          Раздел показывается всегда, даже когда неизмеренных факторов нет:
          пользователь должен видеть, что вопрос задан и на него есть ответ.
          Спрятать раздел значит оставить серый уровень без объяснения.
        */}
        <Section title="Не измерено" icon={AlertTriangle}>
          <p className="mb-3 text-xs text-text-subtle">
            Эти факторы модели остались без значения. Их отсутствие — причина неполноты данных, а
            не признак благополучия объекта.
          </p>
          <UnmeasuredFactors rows={factors.unmeasured} />
        </Section>

        <Section title="Территория" icon={MapPin}>
          {territory.name ? (
            <DefinitionList
              rows={[
                ["Территория", territory.name],
                ["Код территории", territory.code ?? NOT_FILLED],
              ]}
            />
          ) : (
            <p className="text-sm text-text-muted">
              Территория не определена.{" "}
              {asSentence(
                territory.note || "источник не сообщает, почему территорию не удалось определить",
              )}
            </p>
          )}
        </Section>

        <Section title="Сведения объекта">
          <DefinitionList rows={fieldRows} />
        </Section>

        <Section title="Происхождение записи" icon={Database}>
          <DefinitionList rows={provenanceRows} />
        </Section>
      </div>
    </>
  );
}
