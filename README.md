# Интерактивная карта рисков

Backend: Django + GeoDjango + PostgreSQL/PostGIS + DRF (JWT).
Frontend: React + TypeScript + Leaflet + Recharts.
Всё поднимается одним `docker compose` — **один бэкенд, один фронтенд**.

## Запуск окружения (одна команда)

```bash
cp .env.example .env   # уже есть в репозитории со значениями для локальной разработки
docker compose up --build
```

Поднимутся сервисы:
- `db` — PostgreSQL 16 + PostGIS 3.4, порт `5432`
- `redis` — Redis 7, порт `6379`
- `web` — Django, порт `8000` (напрямую) и через nginx
- `frontend` — собирает React в общий том и завершается (это нормально)
- `nginx` — **главная точка входа, порт `80`**: раздаёт фронтенд и проксирует `/api/`, `/admin/`

Открыть: **[http://localhost/](http://localhost/)** — вход `admin` / `admin123`.
Админка Django: [http://localhost/admin/](http://localhost/admin/).

> Фронтенд ходит в API по относительному пути `/api` — порт нигде не зашит.
> Для `npm start` вне докера можно задать `REACT_APP_API_URL`.

## Первый запуск: миграции, данные, пользователи

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py load_boundaries      # границы областей и районов
docker compose exec web python manage.py load_territory_stats # население и площадь
docker compose exec web python manage.py seed_demo_users      # демо-логины под все роли ТЗ
```

`seed_demo_users` создаёт: `admin/admin123` (администратор), `analyst1/analyst123`
(аналитик), `manager1/manager123` (руководитель), `viewer1/viewer123` (просмотр).
Идемпотентна — существующих не трогает.

`load_boundaries` при каждом запуске полностью пересобирает таблицу `Territory`
из файлов-источников (delete + create) — это осознанно, повторный запуск не
плодит дублей. Загружает 20 регионов РК (17 областей + Астана, Алматы, Шымкент)
контуром и 11 районов/городов обл. значения Алматинской области.

`load_territory_stats` запускается **после** `load_boundaries` (он пересоздаёт
Territory, стерев population/area_km2) и обновляет их из
`territories/data/socioeconomic_almaty.json` — площадь всех 17 областей и
площадь+население Алматинской области с районами (источник — stat.gov.kz,
файлы аналитика). Площадь Астаны/Алматы/Шымкента в источнике не приведена,
население областей вне Алматинской — тоже; заполнится позже через
импорт-мастер.

## Импорт тематических слоёв (неделя 2+)

### Субсидии и господдержка (ТЗ п.8.5)

```bash
python manage.py import_subsidies --file subs.xlsx --password 0101 --dry-run
python manage.py import_subsidies --file subs.xlsx --password 0101 --user marzhan
```

Один прогон = полный пересчёт. Читает Excel субсидий, агрегирует **на
получателя** (не на выплату) и пишет: `ThematicLayer` (слой `subsidies`),
`GeoObject` (1 запись на БИН + риск), `RiskFactor` (5 индикаторов —
расшифровка балла, ТЗ п.14), `ImportBatch` (журнал + `error_log` по
непопавшим строкам). Новых таблиц/миграций не требует.

- `--dry-run` — считает и печатает топ-10, в БД не пишет;
- `--password` — файл аналитиков зашифрован (agile encryption), снимается в память;
- идемпотентно: повторный прогон обновляет по `(layer, БИН)`, факторы пересоздаёт;
- всё в одной транзакции.

Важно: в БД лежат **11 районов текущей** Алматинской области (после реформы
2022), а файл аналитиков — по **старой** области. Районы Жетысу и чужих
областей не импортируются, а попадают в `ImportBatch.error_log` с причиной
и суммой (~16% денег вне MVP). Это осознанная граница, не баг.

## API территорий

| Запрос | Что возвращает |
|---|---|
| `GET /api/territories/?level=oblast` | все области РК, GeoJSON FeatureCollection |
| `GET /api/territories/?level=rayon&parent=<id>` | районы области (клик по Алматинской) |
| `GET /api/territories/<id>/` | одна территория (GeoJSON Feature) для карточки |

Ответ — готовый GeoJSON, рисуется на Leaflet через `L.geoJSON()`.
В `properties` каждого объекта: `kato_code`, `name_ru`, `name_kz`, `level`,
`parent`, `population`, `area_km2`.

**`level` — фиксированный словарь на всю команду, единый со схемой в
ER-диаграмме проекта:** `oblast` | `rayon` | `settlement` (населённый пункт,
пока не используется, задел на будущее). Не `region`/`district` — если в
других частях системы (фронт, бюджетный слой) встретится такое значение,
это несовпадение со стандартом, надо поправить на месте, а не заводить
второй словарь.

Пример:

```bash
curl "http://localhost:8000/api/territories/?level=oblast"
```

## API аналитики слоёв (неделя 2+)

Единый контракт (общие query-параметры: `layer`, `year`, `risk_level` CSV,
`territory`/`parent`, `search`). Цвета — только на фронте; бэк отдаёт
`risk_level` строкой (`low`/`medium`/`high`/`critical`/`null`).

| Запрос | Что возвращает |
|---|---|
| `POST /api/token/` | вход: `{username, password}` -> `{access, refresh}` (JWT) |
| `POST /api/token/refresh/` | обновление access-токена |
| `GET /api/layers/` | активные слои для панели (динамическая) |
| `GET /api/territories/risk/?layer=&parent=&year=&risk_level=` | GeoJSON районов с **взвешенным по сумме** риском — заливка карты |
| `GET /api/dashboard/?layer=&territory=&year=` | сводка по области ИЛИ району (ветвится по `territory.level`) |
| `GET /api/geo-objects/?layer=&territory=&risk_level=&year=&search=&ordering=` | список компаний (пагинация 25, `ordering=-risk_score`\|`-paid_total`) |
| `GET /api/geo-objects/<id>/` | карточка + расшифровка балла по `risk_factors` (ТЗ п.14) |

Ключевые решения (детали — в `nedelya_subsidii_plan.md`):
- Риск района — **взвешенный по сумме**, не простое среднее (модуль
  `territories/analytics.py`, общий с импортом — пороги не разъедутся).
- Районы без объектов возвращаются с `risk_level=null`, а не выкидываются —
  иначе на карте дыры.
- `?year=` пересчитывает риск на срезе года (`attributes.by_year`); в списке
  компаний год фильтрует состав, балл показывается итоговый.
- Дашборд даёт **две метрики**: `top_risk` (кто подозрителен) и
  `top_exposure` = сумма × риск (где лежат деньги под риском).

Тесты эндпоинтов: `python manage.py test territories`.

## Данные: источник и ограничения

Границы — **OpenStreetMap** (Overpass API + polygons.openstreetmap.fr), уже
в постреформенных границах (2022 г.): есть Абайская, Жетысуская, Улутауская
области и отдельные Астана/Алматы/Шымкент. КАТО регионов посчитаны из тега
`ISO3166-2` и сверены с [tenderplus.kz/kato](https://tenderplus.kz/kato) —
совпадают. У районов Алматинской области КАТО намеренно не проставлены:
справочная база на уровне районов ещё не синхронизирована с реформой.
Население пока пустое — зальётся через импорт-мастер.
Подробнее и как переехали с GADM: [`backend/territories/data/SOURCE.md`](backend/territories/data/SOURCE.md).

## Схема данных

Поля и имена таблиц зафиксированы по ER-диаграмме проекта — это единый
источник правды для всей команды (аналитики недель 2-5, фронт). Если код и
диаграмма разойдутся — расхождение надо чинить, а не считать нормой.

| Таблица | Ключевые поля |
|---|---|
| `Territory` | `kato_code`, `name_ru`, `name_kz`, `level` (`oblast`\|`rayon`\|`settlement`), `parent`, `geometry`, `population`, `area_km2` |
| `ThematicLayer` | `code`, `name_ru`, `color_hex`, `description`, `is_active`, `sort_order` |
| `GeoObject` | `layer`, `territory`, `external_id`, `source_system`, `imported_at`, `name`, `attributes` (JSON), `geometry`, `risk_score`, `risk_level` |
| `RiskFactor` | `geo_object`, `indicator_code`, `indicator_name`, `raw_value`, `weight`, `contribution`, `calculated_at` — расшифровка расчёта риска по одному объекту (ТЗ п.14), не справочник индикаторов |
| `ImportBatch` | `file_name`, `source_name`, `layer`, `status`, `total_rows`, `imported_rows`, `error_rows`, `error_log` (JSON), `imported_by` |
| `accounts.User` | `username`, `email`, `full_name`, `role` (`admin`\|`analyst`\|`manager`\|`viewer`, ТЗ раздел 5) |

`GeoObject` и `ThematicLayer` спроектированы так, чтобы недели 2-5
(закупки, организации, инфраструктура, бюджет) писали данные в них
**без новых миграций** — поля под источник/импорт/цвет слоя уже заведены.

## Структура

```
backend/                    # ЕДИНСТВЕННЫЙ бэкенд проекта
  manage.py
  riskmap/                  # настройки, settings.py читает .env; JWT + CORS
  accounts/                 # кастомный User (AUTH_USER_MODEL), роли ТЗ
    management/commands/seed_demo_users.py
  territories/              # территории, слои, риски, импорт
    models.py               # Territory, ThematicLayer, GeoObject, RiskFactor, ImportBatch
    analytics.py            # пороги риска + взвешенная агрегация (общий модуль)
    serializers.py / views.py / urls.py / tests.py
    data/                   # границы из OSM (GeoJSON) + SOURCE.md
    management/commands/    # load_boundaries, load_territory_stats, import_subsidies
  requirements.txt
  Dockerfile
frontend/                   # React + TS (карта, дашборд, импорт-мастер)
  src/api/                  # один axios-клиент на относительный /api
  src/pages/ src/components/
  Dockerfile                # собирает build и кладёт в том для nginx
nginx/nginx.conf            # раздаёт фронт, проксирует /api/ и /admin/
docker-compose.yml
.env.example
```

> **Про «много бэкендов»:** в ветке `nuray-dev` какое-то время лежали ещё два
> Django-проекта (`backend/` с приложениями-заглушками и копия `riskmap_backend/`).
> Они возникли потому, что ветка была начата с нуля, без общего предка с `main`.
> В `main` оставлен один бэкенд — этот; дубли не переносились.

## Статус по плану недели 1

- ✅ Пн: репозиторий, docker-compose, окружение одной командой.
- ✅ Вт: модели `Territory`, `ThematicLayer`, `GeoObject`, `RiskFactor`, `ImportBatch`, `accounts.User` (роли), миграции, admin. Схема выверена по ER-диаграмме проекта.
- ✅ Ср: management-команда загрузки границ (области РК контуром + районы Алматинской области).
- ✅ Чт: DRF-эндпоинты `/api/territories/`.
- ⬜ Пт: помощь с импорт-мастером, код-ревью.
