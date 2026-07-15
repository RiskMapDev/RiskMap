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
| `GET /api/territories/?level=region` | все области РК, GeoJSON FeatureCollection |
| `GET /api/territories/?level=district&parent=<id>` | районы области (клик по Алматинской) |
| `GET /api/territories/<id>/` | одна территория (GeoJSON Feature) для карточки |

Ответ — готовый GeoJSON, рисуется на Leaflet через `L.geoJSON()`.
В `properties` каждого объекта: `kato_code`, `name`, `name_en`, `level`,
`parent`, `population`, `area_km2`.

Пример:

```bash
curl "http://localhost:8000/api/territories/?level=region"
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

## Структура

```
backend/
  manage.py
  riskmap/                  # настройки проекта, settings.py читает .env
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
- ✅ Вт: модели `Territory`, `ThematicLayer`, `GeoObject`, `RiskFactor`, `ImportBatch`, миграции, admin.
- ✅ Ср: management-команда загрузки границ (области РК контуром + районы Алматинской области).
- ✅ Чт: DRF-эндпоинты `/api/territories/`.
- ⬜ Пт: помощь с импорт-мастером, код-ревью.
