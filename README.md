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

## Первый запуск миграций и суперпользователя

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

## Структура

```
backend/
  manage.py
  riskmap/          # настройки проекта, settings.py читает .env
  requirements.txt
  Dockerfile
docker-compose.yml
.env.example
```

## Дальше по плану недели 1

- Вт: модели `Territory`, `ThematicLayer`, `GeoObject`, `RiskFactor`, `ImportBatch`, миграции, admin.
- Ср: management-команда загрузки границ (geoBoundaries: все области РК контуром, районы — только Алматинская область).
- Чт: DRF-эндпоинты `/territories/`.
- Пт: помощь с импорт-мастером, код-ревью, README для окружения (этот файл).
