# Next.js 16.2.10 — практическая шпаргалка для команды

Источник: локальная документация `frontend/node_modules/next/dist/docs/`.
Всё, что ниже, взято оттуда. Там, где документация чего-то не покрывает, это прямо отмечено: **«в документации Next не описано»**.

Контекст: Next 16.2.10, React 19.2.4, Tailwind 4, TS strict, App Router, `src/`, alias `@/*`.
Данные — с внешнего FastAPI по HTTP с Bearer-токеном. SSG не используется, нужны всегда свежие данные.

Текущее состояние проекта (проверено):
`next.config.ts` пустой → **`cacheComponents` выключен**; `postcss.config.mjs` уже настроен на `@tailwindcss/postcss`; `src/app/globals.css` уже использует `@import "tailwindcss"` + `@theme inline`; `vitest.config.*` и `playwright.config.*` **ещё не созданы**.

---

## 1. Breaking changes v15 → v16, релевантные проекту

| Что | Было (15) | Стало (16) |
|---|---|---|
| `params`, `searchParams`, `cookies()`, `headers()`, `draftMode()` | можно было читать синхронно (deprecated-совместимость) | **только `await`**, синхронный доступ удалён полностью |
| Сборщик | `next dev --turbopack` | Turbopack по умолчанию для `dev` и `build`. Флаг не нужен |
| Кастомный `webpack` в конфиге | работал | `next build` **падает**, если найден `webpack`-конфиг. Варианты: `--turbopack` (игнорировать), мигрировать, или `next build --webpack` |
| `experimental.turbopack` | внутри `experimental` | верхнеуровневый `turbopack: {}` |
| `middleware.ts` | `middleware.ts`, экспорт `middleware` | **`proxy.ts`**, экспорт `proxy`. Runtime только `nodejs`, edge не поддерживается. Флаги переименованы: `skipMiddlewareUrlNormalize` → `skipProxyUrlNormalize` |
| `revalidateTag('tag')` | один аргумент | **два аргумента обязательны**: `revalidateTag('tag', 'max')`. Один аргумент → ошибка TypeScript |
| `unstable_cacheLife` / `unstable_cacheTag` | с префиксом | стабильны: `import { cacheLife, cacheTag } from 'next/cache'` |
| PPR | `experimental.ppr`, `experimental_ppr` на сегменте | **удалены**. PPR включается только через `cacheComponents: true` |
| `experimental.dynamicIO`, `experimental.useCache` | флаги | заменены одним `cacheComponents: true` |
| `next lint` | была команда, `next build` линтил | **команда удалена**, `next build` больше не линтит. Опция `eslint` в конфиге удалена. Запускать `eslint` напрямую (в проекте: `npm run lint` → `eslint`) |
| ESLint конфиг | `.eslintrc` | `@next/eslint-plugin-next` по умолчанию **flat config** (в проекте уже `eslint.config.mjs`) |
| `serverRuntimeConfig` / `publicRuntimeConfig` | работали | **удалены**. Только env-переменные |
| Parallel routes | `default.js` необязателен | **обязателен для каждого слота**, иначе сборка падает |
| `scroll-behavior: smooth` | Next перебивал его при навигации | больше не перебивает. Вернуть старое поведение: `<html data-scroll-behavior="smooth">` |
| Node.js / TS | Node 18 ок | **Node ≥ 20.9**, **TypeScript ≥ 5.1**. Браузеры: Chrome/Edge/FF 111+, Safari 16.4+ |
| `.next` | одна папка | `next dev` пишет в `.next/dev`, `build` — в `.next`; можно запускать параллельно. Лок-файл запрещает два `dev` на один проект |
| `process.argv` в `next.config` | содержал `'dev'` | при `next dev` **не содержит**. Проверять `process.env.NODE_ENV === 'development'` |
| `next/image` дефолты | — | `minimumCacheTTL` 60s → **4 часа**; `imageSizes` — убран `16`; `qualities` → только `[75]`; редиректы ≤ 3; локальные IP заблокированы (`dangerouslyAllowLocalIP`); локальные картинки с query-строкой требуют `images.localPatterns.search`; `images.domains` deprecated → `remotePatterns` |
| `next/legacy/image` | работал | deprecated |
| AMP | был | удалён целиком |
| `unstable_rootParams` | был | удалён, замены пока нет |
| `next build` вывод | `size`, `First Load JS` | эти метрики убраны как недостоверные для RSC |
| Sass из `node_modules` | `@import '~pkg/...'` | тильда не поддерживается Turbopack: `@import 'pkg/...'` |

Кодмод для миграции: `npx @next/codemod@canary upgrade latest`.

Нового в 16, что стоит знать: `updateTag` (read-your-writes в Server Actions), `refresh()` (обновить клиентский роутер из Server Action), стабильный `reactCompiler: true` (по умолчанию выключен, сборка медленнее — Babel).

---

## 2. Что теперь асинхронно и как типизировать в strict TS

Асинхронны (только `await` / `use()`):
`params` (в `layout`, `page`, `route`, `default`, `opengraph-image`, `twitter-image`, `icon`, `apple-icon`), `searchParams` (только в `page`), `cookies()`, `headers()`, `draftMode()`, а также `id` в `sitemap` и в image-функциях при `generateImageMetadata`.

### Способ 1 (рекомендуемый): глобальные хелперы типов

`PageProps`, `LayoutProps`, `RouteContext` — **глобальные, импорт не нужен**. Генерируются при `next dev`, `next build` или `npx next typegen`. В `tsconfig.json` уже подключены `.next/types/**/*.ts` и `.next/dev/types/**/*.ts`.

```tsx
// src/app/objects/[id]/page.tsx
export default async function Page(props: PageProps<'/objects/[id]'>) {
  const { id } = await props.params          // строго типизировано из литерала маршрута
  const { page = '1' } = await props.searchParams
  return <h1>{id}</h1>
}
```

```tsx
// src/app/dashboard/layout.tsx
export default function Layout(props: LayoutProps<'/dashboard'>) {
  return <section>{props.children}</section>  // именованные слоты (@analytics) тоже типизированы
}
```

```ts
// src/app/api/objects/[id]/route.ts
export async function GET(_req: NextRequest, ctx: RouteContext<'/api/objects/[id]'>) {
  const { id } = await ctx.params
  return Response.json({ id })
}
```

Статические маршруты дают `params: {}`.

### Способ 2: ручная типизация (если типы ещё не сгенерированы)

```tsx
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const { id } = await params
  const sp = await searchParams
}
```

Под strict помните: значение `searchParams` — `string | string[] | undefined`. Для `?risk=high&risk=low` придёт массив. Нормализуйте:

```ts
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v)
const many = (v: string | string[] | undefined) =>
  v === undefined ? [] : Array.isArray(v) ? v : [v]
```

`searchParams` — **обычный объект, не `URLSearchParams`**.

### Client Component-страница

Client-компонент не может быть `async`, поэтому промисы разворачиваются через `use()`:

```tsx
'use client'
import { use } from 'react'

export default function Page({
  searchParams,
}: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { page } = use(searchParams)   // suspend → нужен <Suspense> сверху
}
```

### cookies / headers

```ts
import { cookies, headers } from 'next/headers'

const token = (await cookies()).get('access_token')?.value
const referer = (await headers()).get('referer')
```

`cookies()` возвращает read-only-хранилище в Server Components; `set`/`delete` доступны только в Route Handlers и Server Actions.

---

## 3. Server / Client Components

### Правило по умолчанию

Всё в `app/` — Server Component. `"use client"` ставится **только** там, где нужны: `useState`/`useReducer`, обработчики событий, `useEffect`, браузерные API (`window`, `localStorage`, MapLibre), кастомные хуки, React Context.

### Что означает `"use client"`

Директива объявляет **границу модульного графа**. Всё, что файл импортирует и что он рендерит напрямую, попадает в клиентский бандл. **Не надо** ставить директиву в каждый файл — достаточно на входной точке границы.

Исключение: Server Components, переданные **как `children` или другой проп**, не попадают в клиентский граф — они рендерятся на сервере, а в клиент уходит готовый результат.

### Как прокидывать данные

1. **Пропсами** Server → Client. Пропсы должны быть **сериализуемыми** (React-сериализация): примитивы, plain-объекты, массивы, Date/Map/Set/TypedArray. **Нельзя**: инстансы классов, функции (кроме Server Actions), Symbol, `URL`.
2. **Промисом + `use()`** — стриминг:

```tsx
// server
export default function Page() {
  const rows = getRows()               // НЕ await
  return <Suspense fallback={<Skeleton/>}><Table rows={rows} /></Suspense>
}
```
```tsx
'use client'
import { use } from 'react'
export function Table({ rows }: { rows: Promise<Row[]> }) { const data = use(rows) }
```

3. **Слот `children`** — чтобы вложить серверный контент внутрь клиентской оболочки:

```tsx
// server page
<MapShell>          {/* 'use client' — MapLibre */}
  <LegendPanel />   {/* server component, рендерится на сервере */}
</MapShell>
```

### Чего нельзя

- React Context **не работает в Server Components**. Провайдер (react-query, zustand-провайдер, тема) — это отдельный клиентский компонент с `children`, который импортируется в `layout.tsx`. Рендерить провайдеры **как можно глубже**, не оборачивать весь `<html>`.
- Сторонний компонент без `"use client"`, использующий хуки, нельзя рендерить прямо из Server Component. Обёртка:
  ```tsx
  'use client'
  export { Carousel as default } from 'acme-carousel'
  ```
- Секреты не утекают: в клиентский бандл попадают только `NEXT_PUBLIC_*`; остальные заменяются пустой строкой. **Bearer-токен FastAPI должен читаться только на сервере.** Для гарантии — `import 'server-only'` в модуле доступа к API (пакет опционален; Next даёт свои d.ts).
- Наоборот, `import 'client-only'` — для модулей, трогающих `window`.

### Практика проекта

- Модуль `@/lib/api` (fetch к FastAPI + Bearer) → `import 'server-only'`, только серверные вызовы.
- MapLibre, Cytoscape, ECharts, панель фильтров, мастер импорта — `"use client"`.
- Дашборд/список: страница — Server Component, читает `searchParams`, тянет данные; интерактив (сортировка, чекбоксы) — клиентские листья.
- `React.cache()` — дедупликация одинаковых запросов в пределах одного рендера (для не-`fetch` вызовов). Скоуп — один запрос, между запросами ничего не шарится.

---

## 4. Кэширование

### Что кэшируется по умолчанию в 16

- **`fetch` не кэшируется по умолчанию** и блокирует рендер страницы до завершения.
- Одинаковые `fetch` в дереве **мемоизируются** в пределах одного рендера (это дедупликация, не кэш между запросами).
- **Route Handlers не кэшируются**; кэш `GET` — только явно через `export const dynamic = 'force-static'`. Прочие методы не кэшируются никогда.
- `next/image` теперь кэширует картинки минимум 4 часа (`minimumCacheTTL`).

> Оговорка по документации: в разделе `fetchCache` (продвинутая опция, `caching-without-cache-components.md`) написано, что при `fetchCache: 'auto'` Next «кэширует fetch-запросы, встреченные до вызова Request-time API». Это противоречит основному утверждению «fetch не кэшируется по умолчанию». Не полагайтесь на догадки — **ставьте режим явно**.

### Как гарантированно получать свежие данные (наш случай)

Порядок предпочтения:

1. **Явный `no-store` на каждом запросе** — самое надёжное:
   ```ts
   const res = await fetch(url, { cache: 'no-store', headers: { Authorization: `Bearer ${token}` } })
   ```
2. **`await connection()`** перед доступом к данным — семантически привязывает рендер к входящему запросу:
   ```ts
   import { connection } from 'next/server'
   export default async function Page() { await connection(); /* ... */ }
   ```
   Документация прямо рекомендует `connection()` **вместо** устаревшего приёма `export const dynamic = 'force-dynamic'`.
3. Сегментные настройки (если нужен «рубильник» на весь маршрут): `export const revalidate = 0` или `export const dynamic = 'force-dynamic'` (эквивалентно `cache: 'no-store'` + `fetchCache = 'force-no-store'` для всего сегмента).
4. **Не использовать** `use cache`, `unstable_cache`, `next: { revalidate: N }` на «живых» данных.

Чтение `cookies()`, `headers()`, `searchParams` само по себе делает рендер динамическим.

### `cacheComponents` — что это

`cacheComponents: true` в `next.config.ts` включает модель Cache Components:
- данные **динамические по умолчанию**, кэшируется только то, что явно помечено `use cache`;
- **PPR становится поведением по умолчанию**: Next пререндерит статическую оболочку (shell), динамика стримится;
- становятся доступны `use cache`, `cacheLife`, `cacheTag`;
- при включённом флаге всё, что не может отрендериться на этапе prerender и не обёрнуто в `<Suspense>` и не помечено `use cache`, даёт **ошибку сборки** `Uncached data was accessed outside of <Suspense>`;
- `GET` Route Handlers начинают жить по той же модели (prerender, если не трогают runtime-данные);
- включается React `<Activity>`: при навигации предыдущий маршрут **не размонтируется**, а прячется через `display: none`; state сохраняется, хранится до 3 маршрутов. Эффекты вычищаются при скрытии и создаются заново при показе.

**Рекомендация для нашего проекта:** флаг сейчас выключен — так и оставить на старте. Он даёт строгие требования к расстановке `<Suspense>` и меняет поведение размонтирования, что заденет карту, дропдауны и мастер импорта. Включать — отдельной задачей, с прочтением `preserving-ui-state.md` и `migrating-to-cache-components.md`.

### `use cache` — если всё же включим

```ts
// файл целиком (все экспорты должны быть async)
'use cache'

// или точечно
export async function getDictionary() {
  'use cache'
  cacheLife('hours')
  cacheTag('dict')
  return fetch(...)
}
```

Ключ кэша = build ID + хэш функции + сериализованные аргументы + **захваченные из замыкания переменные**. Ограничения:
- внутри `use cache` **нельзя** вызывать `cookies()`, `headers()`, читать `searchParams`. Читать снаружи и передавать аргументом.
- аргументы/возврат должны быть сериализуемы; нельзя инстансы классов, функции, `URL`, Symbol.
- `children` и Server Actions можно **пропускать насквозь**, если не разворачивать их внутри.
- `React.cache` изолирован: данные из внешнего скоупа внутрь `use cache` не видны.
- профиль по умолчанию: stale 5 мин (клиент), revalidate 15 мин (сервер), без истечения по времени. Клиентский роутер принудительно держит минимум **30 секунд** stale, что бы ни настроили.
- зависание сборки на 50 сек с сообщением «Filling a cache during prerender timed out» = внутрь `use cache` протёк промис с runtime-данными.

Инвалидация: `revalidateTag(tag, profile)` (stale-while-revalidate), `updateTag(tag)` (только в Server Actions, немедленно, read-your-writes), `refresh()` (обновить клиентский роутер).

Отладка: `NEXT_PRIVATE_DEBUG_CACHE=1`.

---

## 5. Route Handlers

Файл `route.ts` в `src/app/**`. **Нельзя** класть `route.ts` и `page.tsx` в один сегмент.
Методы: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`, `OPTIONS` (`OPTIONS` генерируется автоматически). Неподдерживаемый метод → 405.

### Сигнатуры

```ts
import type { NextRequest } from 'next/server'

export async function GET(request: NextRequest) {
  const q = request.nextUrl.searchParams.get('query')
  return Response.json({ q })
}

// с динамическим сегментом — params это Promise
export async function GET(_req: NextRequest, ctx: RouteContext<'/api/reports/[id]'>) {
  const { id } = await ctx.params
}
```

### FormData и загрузка файлов (мастер импорта)

```ts
export async function POST(request: Request) {
  const formData = await request.formData()
  const file = formData.get('file')          // File | FormDataEntryValue | null
  if (!(file instanceof File)) {
    return Response.json({ error: 'file required' }, { status: 400 })
  }
  // проксирование в FastAPI без буферизации всего тела в памяти:
  const upstream = new FormData()
  upstream.append('file', file, file.name)
  const res = await fetch(`${API}/import`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },  // Content-Type НЕ ставить — boundary выставится сам
    body: upstream,
  })
  return new Response(res.body, { status: res.status, headers: res.headers })
}
```

`bodyParser`-конфига, как в Pages Router, **не нужно**. Все значения `formData` — строки (кроме файлов); для валидации документация советует `zod-form-data` (в проекте есть `zod`).

**Лимит размера загружаемого файла в Route Handler в документации Next не описан** — уточнять на стороне сервера/прокси.

### Стриминг

```ts
export async function GET() {
  const stream = new ReadableStream({
    async pull(controller) {
      const { value, done } = await iterator.next()
      done ? controller.close() : controller.enqueue(value)
    },
  })
  return new Response(stream)
}
```

Проще всего для отчётов — пробросить тело апстрима: `return new Response(upstream.body, { headers })`.

### Бинарные файлы (отчёты)

Отдельного API для файлов нет — стандартный Web `Response` с нужными заголовками:

```ts
export async function GET(_req: NextRequest, ctx: RouteContext<'/api/reports/[id]'>) {
  const { id } = await ctx.params
  const upstream = await fetch(`${API}/reports/${id}.xlsx`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  })
  if (!upstream.ok) return new Response('Not found', { status: 404 })

  return new Response(upstream.body, {          // стрим, без буферизации
    status: 200,
    headers: {
      'Content-Type':
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'Content-Disposition': `attachment; filename="report-${id}.xlsx"`,
      'Cache-Control': 'no-store',
    },
  })
}
```

`Response` принимает `ReadableStream`, `ArrayBuffer`, `Blob`, `Uint8Array`, строку. Cookies — через `cookies()` из `next/headers` или заголовок `Set-Cookie`. CORS — вручную в заголовках либо через `proxy.ts` / `headers` в `next.config`.

Сегментные конфиги те же, что у страниц: `dynamic`, `revalidate`, `runtime`, `fetchCache`, `dynamicParams`, `preferredRegion`.

---

## 6. `useSearchParams` — подводные камни

- Только Client Component. В Server Components **не поддерживается** (защита от устаревших значений при частичном рендере).
- Возвращает **read-only** `URLSearchParams`. Менять — только через навигацию.
- **Layout не получает проп `searchParams`** — вообще. Layout не перерендеривается при клиентской навигации, поэтому значения были бы устаревшими. Если фильтры нужны в layout-подобной оболочке (панель фильтров над картой и списком) — это клиентский компонент с `useSearchParams`, а не серверный layout.

### Требование Suspense (иначе падает прод-сборка)

> В dev маршруты рендерятся по требованию, поэтому **без `<Suspense>` всё выглядит рабочим**. При `next build` статическая страница, вызывающая `useSearchParams` из клиентского компонента, падает с ошибкой **«Missing Suspense boundary with useSearchParams»**.

Правило: **любой клиентский компонент с `useSearchParams` оборачивается в `<Suspense>` с осмысленным fallback.**

```tsx
import { Suspense } from 'react'

export default function Page() {
  return (
    <Suspense fallback={<FiltersSkeleton />}>
      <FilterBar />     {/* 'use client' + useSearchParams */}
    </Suspense>
  )
}
```

Альтернатива для заведомо динамических маршрутов — `await connection()` в серверной странице до рендера: это исключает всё нижележащее из prerender. Предпочитать `connection()`, а не устаревший `dynamic = 'force-dynamic'`.

### Обновление параметров (наш кейс: фильтры в URL, синхронно для карты и списка, с back/forward)

```tsx
'use client'
import { useCallback } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'

const searchParams = useSearchParams()
const pathname = usePathname()
const router = useRouter()

const setParam = useCallback((name: string, value: string) => {
  const params = new URLSearchParams(searchParams.toString())
  params.set(name, value)
  return params.toString()
}, [searchParams])

router.push(pathname + '?' + setParam('sort', 'asc'))
// или <Link href={pathname + '?' + setParam('sort','desc')}>
```

После навигации текущий `page.tsx` получает обновлённый проп `searchParams`. Back/forward работают штатно, потому что состояние живёт в URL — это и есть причина держать фильтры там.

### Что где использовать

- `searchParams` (проп страницы) — когда параметры нужны **для загрузки данных** (пагинация списка, фильтры для запроса к FastAPI).
- `useSearchParams` — когда параметры нужны **только на клиенте** (подсветка активного фильтра, состояние карты).
- `new URLSearchParams(window.location.search)` — в обработчиках событий, когда не нужен ререндер.

---

## 7. Tailwind CSS 4 в Next 16

### Подключение (в проекте уже сделано)

```bash
npm i -D tailwindcss @tailwindcss/postcss
```

```js
// postcss.config.mjs
const config = { plugins: { '@tailwindcss/postcss': {} } }
export default config
```

```css
/* src/app/globals.css */
@import 'tailwindcss';
```

```tsx
// src/app/layout.tsx
import './globals.css'
```

### Что изменилось

- **`tailwind.config.js` нет.** Плагин PostCSS называется `@tailwindcss/postcss` (не `tailwindcss`), подключение — одной строкой `@import 'tailwindcss'` вместо трёх `@tailwind base/components/utilities`.
- Секция `content` с путями (и, соответственно, префикс `/src`) больше не нужна — упоминания `tailwind.config.js` в документации Next относятся только к **Tailwind v3** (`guides/tailwind-v3-css.md`) и к миграционным гайдам. Не копируйте оттуда.
- Конфигурация живёт в CSS.

### Кастомные токены через `@theme`

Документация Next показывает `@theme` только на примере шрифтов (`api-reference/components/font.md`):

```css
@import 'tailwindcss';

@theme inline {
  --font-sans: var(--font-inter);
  --font-mono: var(--font-roboto-mono);
}
```

Смысл: переменная с namespace-префиксом (`--color-*`, `--font-*`, `--radius-*`, `--spacing-*`) порождает соответствующие утилиты (`bg-*`, `text-*`, `font-*`, `rounded-*`). `inline` означает, что значение подставляется как есть — именно это позволяет ссылаться на runtime-переменные тем.

В проекте это уже реализовано в `src/app/globals.css`: цвета определены в `:root` / `[data-theme="dark"]`, а `@theme inline` пробрасывает их в утилиты (`--color-risk-high` → `bg-risk-high`, `text-risk-high`). **Придерживайтесь этой схемы, новые токены добавляйте в оба блока.**

> **Полный список namespace'ов `@theme` и остальные директивы Tailwind 4 (`@utility`, `@variant`, `@custom-variant`) в документации Next не описаны** — это документация Tailwind.

### Прочее по CSS

- CSS Modules (`*.module.css`) работают, порядок стилей определяется **порядком импортов**. Отключите авто-сортировку импортов в линтере/форматтере (`sort-imports`), иначе поедет каскад.
- Порядок CSS в dev и prod может отличаться — проверять на `next build`.
- Глобальные стили при навигации не выгружаются; глобальным держать только по-настоящему глобальное.
- CSS сторонних пакетов (`maplibre-gl/dist/maplibre-gl.css`) импортируется где угодно в `app/`; логичное место — root layout.
- Тонкая настройка чанкинга — `cssChunking` в `next.config`.

---

## 8. Vitest и Playwright

### Vitest

Пакеты (в проекте уже установлены `vitest@4`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/*`):

```bash
npm i -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom vite-tsconfig-paths
```

**`vite-tsconfig-paths` обязателен** для TS-проекта — без него не резолвится alias `@/*`. Его в проекте **нет**, добавить.

```ts
// vitest.config.mts   ← именно .mts, как в документации
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: { environment: 'jsdom' },
})
```

```json
"scripts": { "test": "vitest" }
```

Тесты — в `__tests__/` или рядом с кодом в `app/`.

**Главное ограничение:** > «async Server Components не поддерживаются Vitest». Юнит-тестами покрываются только **синхронные** Server Components и Client Components. Для async-серверных компонентов документация рекомендует **E2E**.

Что это значит на практике:
- Vitest — на чистые модули: нормализация фильтров из URL, парсинг ответов FastAPI (zod-схемы), утилиты пагинации, преобразование геоданных, презентационные Client Components (панель фильтров, таблица, легенда карты).
- Страницы, которые `await`-ят данные, — в Playwright.

Типовые ошибки:
- Нет `vite-tsconfig-paths` → «Cannot find module '@/...'».
- `@testing-library/jest-dom` установлен, но матчеры не подключены: нужен `test.setupFiles` с `import '@testing-library/jest-dom/vitest'`. **В документации Next это не описано** — смотрите документацию Testing Library.
- Попытка отрендерить `async function Page()` — тест либо падает, либо получает промис вместо разметки.
- `msw` в проекте есть — мокать HTTP к FastAPI им, а не патчить глобальный `fetch`.

### Playwright

```bash
npm init playwright     # создаёт playwright.config.ts
```

`@playwright/test` в проекте установлен, **`playwright.config.ts` отсутствует** — создать.

Документация настаивает: **гонять E2E против продакшн-сборки**, а не dev-сервера — `npm run build && npm run start`, затем `npx playwright test`. Альтернатива — опция `webServer` в конфиге, чтобы Playwright сам поднимал сервер и ждал готовности.

Задать `baseURL: 'http://localhost:3000'`, тогда `page.goto('/')` вместо полных URL.

```ts
// tests/example.spec.ts
import { test, expect } from '@playwright/test'

test('переход на список объектов', async ({ page }) => {
  await page.goto('/')
  await page.click('text=Объекты')
  await expect(page).toHaveURL('/objects')
  await expect(page.locator('h1')).toContainText('Объекты')
})
```

CI: headless по умолчанию, зависимости — `npx playwright install-deps`.

Типовые ошибки:
- Прогон против `next dev`: в dev страницы всегда рендерятся по требованию, поэтому проблемы с `useSearchParams`/Suspense и prerender-ошибки **не воспроизводятся**. Ловить их можно только на прод-сборке.
- Не забыть, что `next dev` и `next build` теперь пишут в разные папки (`.next/dev` и `.next`) — параллельный запуск допустим.

**Дополнительно (только при `cacheComponents: true`)**: пакет `@next/playwright` даёт хелпер `instant(page, cb)` — проверяет, что именно попадает в статическую оболочку до стриминга динамики. Пока флаг выключен — неприменимо.

---

## 9. Грабли: где ошибётесь, если писать по памяти о Next 14/15

1. **Синхронный `params.id` / `searchParams.q`.** В 16 это Promise, совместимости больше нет. Всегда `await`.
2. **`cookies()` / `headers()` без `await`.** То же самое.
3. **`useSearchParams` без `<Suspense>`.** В `next dev` работает, `next build` падает. Проверяйте прод-сборкой, а не глазами.
4. **Ожидание, что `fetch` кэшируется сам.** Не кэшируется, но и не гарантируется обратное — ставьте `cache: 'no-store'` явно.
5. **`revalidateTag('tag')` с одним аргументом.** Ошибка TypeScript. Нужен профиль: `revalidateTag('tag', 'max')`. Для мгновенного обновления — `updateTag` в Server Action.
6. **`middleware.ts`.** Файл переименован в `proxy.ts`, функция — `proxy`, edge-runtime не поддерживается.
7. **`next lint`.** Команды нет, `next build` не линтит. Линт — отдельный шаг CI.
8. **`export const dynamic = 'force-dynamic'` как рефлекс.** Документация 16 рекомендует `await connection()` — точнее по смыслу и не выключает prerender у всей страницы.
9. **`experimental_ppr` на сегменте.** Удалён. PPR = `cacheComponents: true`.
10. **`serverRuntimeConfig` / `publicRuntimeConfig` и `getConfig()`.** Удалены. Только env. Чтобы переменная читалась в рантайме, а не вшивалась в сборку, вызовите `await connection()` перед чтением `process.env`.
11. **`searchParams` в layout.** Его там нет и не будет. Только `page` или клиентский хук.
12. **`tailwind.config.js`.** Его нет в Tailwind 4. Не заводите, ищите примеры для v4, а не v3-гайды из тех же доков.
13. **`next/image`: картинка «размылилась» или 400.** Новые дефолты: `qualities: [75]` (значение `quality` приводится к ближайшему разрешённому), убран размер 16, локальные IP и локальные картинки с query-строкой блокируются.
14. **Parallel routes без `default.tsx`.** Сборка падает. Класть `default.tsx` с `notFound()` или `return null` в каждый слот.
15. **Кастомный webpack-конфиг или плагин, который его добавляет.** `next build` падает; собирайте с `--webpack` или мигрируйте на `turbopack`.
16. **`~` в Sass-импортах из `node_modules`.** Turbopack не поддерживает.
17. **`process.argv.includes('dev')` в `next.config.ts`.** Больше не срабатывает: `next dev` не грузит конфиг дважды. Использовать `NODE_ENV`.
18. **`scroll-behavior: smooth` в глобальном CSS.** Next больше не подменяет его при навигации — переходы могут «доезжать» плавно. Вернуть старое поведение: `data-scroll-behavior="smooth"` на `<html>`.
19. **`await` подряд вместо `Promise.all`.** Внутри одного компонента последовательные `await` сериализуются. Для дашборда стартуйте все запросы сразу и собирайте `Promise.all` (или `allSettled`, чтобы одна упавшая панель не убила страницу).
20. **`loading.tsx` не спасает layout.** Если layout читает `cookies()`/`headers()`/некэшированные данные, `loading.tsx` того же сегмента **не показывается** — навигация блокируется до готовности layout. Оборачивайте такие места в собственный `<Suspense>` или переносите загрузку в `page.tsx`.
21. **Инстанс класса или `URL` в пропсах Client Component.** Не сериализуется — ошибка. Передавайте plain-объекты и строки.
22. **`import 'server-only'` забыт в модуле с Bearer-токеном.** Компилятор не остановит случайный импорт из клиентского компонента, а токен молча превратится в пустую строку.
23. **Провайдер контекста вокруг `<html>`.** Оборачивайте только `{children}`, иначе теряется статическая оптимизация серверной части.
24. **При включении `cacheComponents`** — сюрприз с `<Activity>`: страницы не размонтируются при навигации, дропдауны и диалоги возвращаются открытыми, эффекты перезапускаются. Сбрасывать транзиентное состояние в cleanup `useLayoutEffect`. Плюс появится обязательное требование `<Suspense>`/`use cache` под угрозой ошибки сборки.
