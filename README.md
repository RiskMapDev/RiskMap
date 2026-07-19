# Аналитическая карта Алматинской области (АКМ)

## Запуск проекта

### Быстрый старт
```bash
cd /Users/nuraiaitbazar/Desktop/mapping
./start.sh
```

### Вручную

**Backend (Django):**
```bash
cd /Users/nuraiaitbazar/Desktop/mapping
source venv/bin/activate
python manage.py runserver 8000
```

**Frontend (React):**
```bash
cd /Users/nuraiaitbazar/Desktop/mapping/frontend
npm start
```

## Доступ

| Сервис    | URL                                |
|-----------|------------------------------------|
| Frontend  | http://localhost:3000              |
| Backend   | http://localhost:8000              |
| Admin     | http://localhost:8000/admin        |
| API docs  | http://localhost:8000/api/v1/      |

**Логин:** `admin` / **Пароль:** `admin123`

## Структура проекта

```
mapping/
├── venv/                    # Python virtualenv
├── config/                  # Django конфиг, URLs, Celery
├── accounts/                # Пользователи, роли
├── regions/                 # Районы, НП, должностные лица
├── budget/                  # Бюджетные программы
├── procurement/             # Государственные закупки
├── construction/            # Объекты строительства
├── agro/                    # АПК, субсидии
├── entities/                # Юр./физ. лица, граф связей
├── risks/                   # Материалы рисков
├── osms/                    # Медорганизации, ОСМС
├── subsoil/                 # Недропользование
├── analytics/               # Дашборд, агрегаты
├── frontend/                # React TypeScript app
│   └── src/
│       ├── api/             # React Query hooks, Axios
│       ├── components/      # Map, Cards, Dashboard, UI
│       ├── pages/           # Login, Map
│       ├── stores/          # Zustand state
│       └── types/           # TypeScript interfaces
├── seed_data.py             # Тестовые данные
├── start.sh                 # Скрипт запуска
└── db.sqlite3               # База данных (SQLite)
```

## API эндпоинты

```
POST /api/v1/auth/token/              # Получить JWT токен
POST /api/v1/auth/token/refresh/      # Обновить токен

GET  /api/v1/regions/districts/       # Список районов
GET  /api/v1/regions/districts/{id}/  # Детальная карточка района
GET  /api/v1/budget/programs/         # Бюджетные программы
GET  /api/v1/procurement/contracts/   # Договоры госзакупок
GET  /api/v1/construction/objects/    # Объекты строительства
GET  /api/v1/agro/recipients/         # Получатели субсидий
GET  /api/v1/entities/legal/          # Юридические лица
GET  /api/v1/entities/legal/{id}/graph/ # Граф связей
GET  /api/v1/risks/materials/         # Риски
GET  /api/v1/osms/organizations/      # Медорганизации
GET  /api/v1/subsoil/sites/           # Участки недропользования
GET  /api/v1/analytics/dashboard/     # Дашборд (агрегаты)
GET  /api/v1/analytics/map-risks/     # Риски на карту
```

## Роли пользователей

| Роль        | Доступ                                    |
|-------------|-------------------------------------------|
| admin       | Полный доступ, управление пользователями  |
| analyst     | Все слои, добавление материалов, экспорт  |
| manager     | Просмотр дашборда и ключевых рисков       |
| viewer      | Только просмотр утверждённых данных       |

## Технологии

**Backend:** Django 4.2, Django REST Framework, SQLite (→ PostGIS в prod)
**Frontend:** React 18, TypeScript, Tailwind CSS, React Query, Zustand
**Auth:** JWT (djangorestframework-simplejwt)
**Отчёты:** openpyxl (Excel), reportlab (PDF)
**Async:** Celery + Redis (для отчётов)

## Продакшн

1. Заменить SQLite на PostgreSQL + PostGIS
2. Настроить `.env` с реальными секретами
3. Запустить Redis для Celery
4. `python manage.py collectstatic`
5. Использовать Gunicorn + Nginx
