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

`load_boundaries` идемпотентна — повторный запуск обновляет записи, дублей не создаёт.
Загружает 14 областей РК (контуром) и 17 районов Алматинской области.

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

Границы — GADM 3.6 через [geo-boundaries-kz](https://github.com/open-data-kazakhstan/geo-boundaries-kz),
КАТО-коды — с [tenderplus.kz/kato](https://tenderplus.kz/kato).

Важно: геометрия **дореформенная** (до 2022 г.), а КАТО — **актуальные**.
Совпадение идёт по названию, поэтому код отражает текущее деление, а полигон —
старое. Население пока пустое — зальётся через импорт-мастер.
Подробнее: [`backend/territories/data/SOURCE.md`](backend/territories/data/SOURCE.md).

## Структура

```
backend/
  manage.py
  riskmap/                  # настройки проекта, settings.py читает .env
  territories/              # территории, слои, риски, импорт
    models.py               # Territory, ThematicLayer, GeoObject, RiskFactor, ImportBatch
    reference_data.py       # рус. названия + КАТО-коды
    serializers.py / views.py / urls.py
    data/                   # исходные границы (GeoJSON) + SOURCE.md
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
