# Интерактивная карта рисков — backend

Django + GeoDjango + PostgreSQL/PostGIS + DRF. Redis поднят как заглушка под будущий кэш/очереди.

## Запуск окружения (одна команда)

```bash
cp .env.example .env   # уже сделано в репозитории со значениями по умолчанию для локальной разработки
docker compose up --build
```

Поднимутся три сервиса:
- `db` — PostgreSQL 16 + PostGIS 3.4, порт `5432`
- `redis` — Redis 7, порт `6379`
- `web` — Django dev-сервер, порт `8000`

Проверить: [http://localhost:8000/admin/](http://localhost:8000/admin/)

## Первый запуск: миграции, данные, админка

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py load_boundaries   # границы областей и районов
docker compose exec web python manage.py createsuperuser   # доступ в /admin/
```

`load_boundaries` при каждом запуске полностью пересобирает таблицу `Territory`
из файлов-источников (delete + create) — это осознанно, повторный запуск не
плодит дублей. Загружает 20 регионов РК (17 областей + Астана, Алматы, Шымкент)
контуром и 11 районов/городов обл. значения Алматинской области.

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
backend/
  manage.py
  riskmap/                  # настройки проекта, settings.py читает .env
  accounts/                 # кастомный User (AUTH_USER_MODEL), роли
  territories/              # территории, слои, риски, импорт
    models.py               # Territory, ThematicLayer, GeoObject, RiskFactor, ImportBatch
    serializers.py / views.py / urls.py
    data/                   # границы из OSM (GeoJSON) + SOURCE.md
    management/commands/load_boundaries.py
  requirements.txt
  Dockerfile
docker-compose.yml
.env.example
```

## Статус по плану недели 1

- ✅ Пн: репозиторий, docker-compose, окружение одной командой.
- ✅ Вт: модели `Territory`, `ThematicLayer`, `GeoObject`, `RiskFactor`, `ImportBatch`, `accounts.User` (роли), миграции, admin. Схема выверена по ER-диаграмме проекта.
- ✅ Ср: management-команда загрузки границ (области РК контуром + районы Алматинской области).
- ✅ Чт: DRF-эндпоинты `/api/territories/`.
- ⬜ Пт: помощь с импорт-мастером, код-ревью.
