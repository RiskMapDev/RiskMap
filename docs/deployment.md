# Развёртывание с нуля

Инструкция воспроизводит рабочее состояние системы на чистой машине: локальный
PostgreSQL с PostGIS **без Docker и без прав администратора**, миграции,
загрузка данных, запуск backend и frontend.

Все команды — PowerShell, обычный (не повышенный) сеанс. Ничего не пишется в
`C:\Program Files`, `C:\Windows` или реестр.

Смежные документы: [архитектура](architecture.md),
[допущения и пробелы](assumptions-and-gaps.md). Первичный аудит установки —
[`docs/audit/07-lokalnyy-postgis.md`](audit/07-lokalnyy-postgis.md).

---

## 0. Предварительные требования

| Компонент | Версия | Проверка |
|---|---|---|
| Python | ≥ 3.12 (проверено на 3.14.0) | `python --version` |
| Node.js | ≥ 20 | `node --version` |
| PostgreSQL | 18.4 | ставится ниже |
| PostGIS | 3.6.2 | ставится ниже |

Дисковое пространство: около 1.5 ГБ на PostgreSQL + PostGIS, около 500 МБ на
`node_modules`.

---

## 1. PostgreSQL 18.4 + PostGIS 3.6.2 без прав администратора

### Почему именно так

Установщики EnterpriseDB и `postgis-bundle-pg18x64-setup-*.exe` требуют UAC и
пишут в системные каталоги и реестр. ZIP-варианты распаковываются в домашний
каталог пользователя и не требуют никаких привилегий.

Мажорные версии обязаны совпадать: бандл `postgis-bundle-pg18-*` собран именно
под PG 18, расширение сообщает `PGSQL="180"`.

### 1.1. Скачивание

```powershell
$sp = "$env:TEMP\pg-install"
New-Item -ItemType Directory -Force -Path $sp | Out-Null
$ProgressPreference = 'SilentlyContinue'   # иначе Invoke-WebRequest очень медленный

# PostgreSQL 18.4 binaries (~322 МиБ)
Invoke-WebRequest -Uri "https://sbp.enterprisedb.com/getfile.jsp?fileid=1260303" `
    -OutFile "$sp\pg18-binaries.zip" -UseBasicParsing -TimeoutSec 900

# PostGIS 3.6.2 bundle (~118 МиБ) + опубликованная контрольная сумма
Invoke-WebRequest -Uri "https://download.osgeo.org/postgis/windows/pg18/postgis-bundle-pg18-3.6.2x64.zip" `
    -OutFile "$sp\postgis-bundle-pg18-3.6.2x64.zip" -UseBasicParsing -TimeoutSec 900
Invoke-WebRequest -Uri "https://download.osgeo.org/postgis/windows/pg18/postgis-bundle-pg18-3.6.2x64.zip.md5" `
    -OutFile "$sp\postgis-bundle-pg18-3.6.2x64.zip.md5" -UseBasicParsing -TimeoutSec 60
```

### 1.2. Проверка контрольных сумм

```powershell
# MD5 PostGIS — должен совпасть с содержимым .md5-файла
Get-Content "$sp\postgis-bundle-pg18-3.6.2x64.zip.md5"
(Get-FileHash "$sp\postgis-bundle-pg18-3.6.2x64.zip" -Algorithm MD5).Hash

# SHA-256 обоих архивов
(Get-FileHash "$sp\postgis-bundle-pg18-3.6.2x64.zip" -Algorithm SHA256).Hash
(Get-FileHash "$sp\pg18-binaries.zip"                -Algorithm SHA256).Hash
```

Эталонные значения, зафиксированные при первой установке:

| Файл | Размер, байт | SHA-256 |
|---|---:|---|
| `pg18-binaries.zip` | 337 445 815 | `02E239529ED7833D169F98D915D3FEFFE0813264B08B3AE353E78E8B9C97E1A6` |
| `postgis-bundle-pg18-3.6.2x64.zip` | 124 037 332 | `0F41241CC536F7404DDA43FD2A3F20FFE1FA1D71A8D4F6341428CD25931BF419` |

MD5 бандла PostGIS — `9e28723541938d1b1a8efb59a5922741`, **опубликован
издателем и совпал**.

> EnterpriseDB **не публикует** контрольные суммы для своих ZIP — сверить было
> не с чем. SHA-256 выше зафиксирован постфактум для воспроизводимости: если вы
> скачаете тот же файл и получите другой хеш, файл изменился.

### 1.3. Распаковка

Архив PostgreSQL содержит корневую папку `pgsql/`, поэтому распаковываем в
домашний каталог, чтобы получить `<HOME>\pgsql`.

```powershell
$PG = "$env:USERPROFILE\pgsql"

Expand-Archive -Path "$sp\pg18-binaries.zip" -DestinationPath "$env:USERPROFILE" -Force

# Бандл PostGIS распаковываем во временную папку...
Expand-Archive -Path "$sp\postgis-bundle-pg18-3.6.2x64.zip" -DestinationPath "$sp\pgis" -Force

# ...и накладываем его содержимое (bin/ lib/ share/ gdal-data/ ...) поверх дерева PostgreSQL
Copy-Item -Path "$sp\pgis\postgis-bundle-pg18-3.6.2x64\*" `
          -Destination $PG -Recurse -Force

# Проверка
& "$PG\bin\postgres.exe" --version          # -> postgres (PostgreSQL) 18.4
Get-ChildItem "$PG\share\extension\postgis*.control"
```

### 1.4. Инициализация кластера

```powershell
& "$PG\bin\initdb.exe" `
    -D "$PG\data" `
    -U postgres --encoding=UTF8 --locale=C --auth=trust
```

> **`--auth=trust` допустим только для локального dev-кластера на loopback.**
> Пароль не требуется, и это сознательное упрощение среды разработки. Для чего
> угодно другого так делать нельзя — см. § 8.

### 1.5. Запуск сервера на порту 5433

`GDAL_DATA` и `PROJ_LIB` задаются **до** запуска: серверный процесс наследует
их от `pg_ctl`. Без них не работает часть функционала `postgis_raster`.

```powershell
$env:GDAL_DATA = "$PG\gdal-data"
$env:PROJ_LIB  = "$PG\share\contrib\postgis-3.6\proj"

& "$PG\bin\pg_ctl.exe" `
    -D "$PG\data" `
    -l "$PG\logfile.txt" `
    -o "-p 5433 -c listen_addresses=127.0.0.1" start
```

Порт 5433 выбран нестандартным, чтобы не конфликтовать с возможной будущей
штатной установкой PostgreSQL на 5432.

### 1.6. Создание базы и расширения

```powershell
$env:PGHOST = "127.0.0.1"; $env:PGPORT = "5433"; $env:PGUSER = "postgres"

& "$PG\bin\createdb.exe" riskmap
& "$PG\bin\psql.exe" -d riskmap -c "CREATE EXTENSION postgis;"
& "$PG\bin\psql.exe" -d riskmap -A -t -c "SELECT postgis_full_version();"
```

Ожидаемый результат — строка вида
`POSTGIS="3.6.2" ... USE_GEOS=1 USE_PROJ=1 USE_STATS=1`.

### 1.7. Управление сервером

```powershell
# статус
& "$PG\bin\pg_ctl.exe" -D "$PG\data" status

# остановка
& "$PG\bin\pg_ctl.exe" -D "$PG\data" stop

# перезапуск
& "$PG\bin\pg_ctl.exe" -D "$PG\data" restart -o "-p 5433 -c listen_addresses=127.0.0.1"

# лог
Get-Content "$PG\logfile.txt" -Tail 40
```

---

## 2. Backend: зависимости

```powershell
cd <репозиторий>\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Устанавливаются, в частности: `fastapi`, `uvicorn[standard]`, `pydantic` 2,
`sqlalchemy` ≥ 2.0.51, `alembic`, `psycopg[binary]` 3, `geoalchemy2`, `shapely`,
`openpyxl`, `python-docx`, `pyjwt`, `argon2-cffi`, `reportlab`.

`reportlab` — **обязательная**, а не дополнительная зависимость: ТЗ требует
выгрузку в PDF. Без него эндпоинт PDF отвечает честным `501`.

---

## 3. Переменные окружения

Настройки читаются из окружения либо из `.env` в корне репозитория или в
`backend/.env` (файл в `.gitignore` и в репозитории отсутствует).

### Backend

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `ENVIRONMENT` | `dev` | `dev` / `test` / `prod` |
| `DEBUG` | `false` | Подробный вывод |
| `DATABASE_URL` | `postgresql+psycopg://postgres@127.0.0.1:5433/riskmap` | Строка подключения |
| `DB_ECHO` | `false` | Логирование SQL |
| `DB_POOL_SIZE` | `10` | Размер пула |
| `DB_MAX_OVERFLOW` | `20` | Переполнение пула |
| `SOURCE_DATA_DIR` | `C:\Users\erbot\Downloads\ДЭР` | **Каталог неизменяемых исходников.** Приложение только читает его |
| `DATA_DIR` | `<репозиторий>\data` | Рабочий каталог: манифест, границы, шрифты |
| `JWT_SECRET` | пусто | **Обязателен при `ENVIRONMENT=prod`** |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_TTL_MINUTES` | `60` | Тайм-аут сессии (требование ТЗ) |
| `PASSWORD_MIN_LENGTH` | `12` | |
| `LOGIN_MAX_ATTEMPTS` | `5` | Блокировка после серии неудач (требование ТЗ) |
| `LOGIN_LOCKOUT_MINUTES` | `15` | |
| `CORS_ORIGINS` | `http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:3001`, `http://127.0.0.1:3001` | |
| `API_PREFIX` | `/api/v1` | |
| `MAX_UPLOAD_MB` | `50` | Ограничение мастера импорта |
| `MAX_PAGE_SIZE` | `200` | Верхняя граница постраничности |

**Про `JWT_SECRET`.** В `prod` пустой секрет — отказ старта с подсказкой. В
`dev`/`test` генерируется временный на процесс. Молчаливая подстановка
постоянного значения по умолчанию была бы худшим вариантом: она превращает
забытую переменную в уязвимость, которую никто не заметит.

```powershell
# сгенерировать секрет
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Про `CORS_ORIGINS`.** `localhost` и `127.0.0.1` — **разные источники** с точки
зрения браузера, и разрешение одного не действует на другой. Оба нужны, потому
что dev-сервер и прод-сборка запускаются по-разному и на разных портах.

### Frontend

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8100/api/v1` | Адрес backend |
| `NEXT_PUBLIC_MAP_STYLE_URL` | не задана | Адрес **своего** тайл-сервера |

Если `NEXT_PUBLIC_MAP_STYLE_URL` не задана, подложки нет вовсе: карта рисует
только собственные границы поверх однотонного фона. Это штатный режим для
закрытого контура. **Внешние публичные сервисы сюда подставлять не следует.**

---

## 4. Миграции

```powershell
cd <репозиторий>\backend
alembic upgrade head
```

Alembic берёт строку подключения из настроек приложения
(`alembic/env.py` вызывает `get_settings().sqlalchemy_url`), поэтому
`sqlalchemy.url` в `alembic.ini` пуст — задавать его отдельно не нужно.

Две ревизии:

| Ревизия | Содержание |
|---|---|
| `d16e7f08d828` | Начальная схема |
| `82058b2d49df` | Связи сущностей (граф) |

Текущая голова — `82058b2d49df`.

Проверка результата:

```powershell
& "$PG\bin\psql.exe" -d riskmap -c "\dt"
& "$PG\bin\psql.exe" -d riskmap -A -t -c "select count(*) from pg_tables where schemaname='public'"
```

Ожидается **40** таблиц: 37 моделей + `role_permissions` + `alembic_version` +
`spatial_ref_sys` (системная таблица PostGIS).

---

## 5. Загрузка данных

Порядок обязателен: слои привязываются к территориям, граф строится из слоёв.

### 5.1. Манифест исходников

```powershell
cd <репозиторий>\backend
python -m scripts.source_manifest build      # зафиксировать SHA-256 всех файлов
python -m scripts.source_manifest verify     # убедиться, что ничего не менялось
```

`verify` возвращает ненулевой код, если файл изменился, исчез или появился
новый. Это единственный способ доказать, что импорт не трогает оригиналы.

### 5.2. Территории, границы, население

```powershell
python -m scripts.load_territories --dry-run   # показать, ничего не записывая
python -m scripts.load_territories
```

Сухой прогон выполняет **ровно те же вставки и те же запросы PostGIS**, что и
обычный, и в конце откатывает транзакцию. Это дороже, чем «предсказать» план по
файлам, но только так отчёт показывает настоящий результат: расхождение
площадей, починку геометрий и итог контрольных сумм нельзя узнать, не выполнив
запросы.

Скрипт сверяет SHA-256 файлов границ с зафиксированными в
`data/boundaries/PROVENANCE.md`. Если файл изменился, импорт **останавливается**.

Ожидаемый результат: 32 территории, 31 геометрия, 2 версии границ, 124 алиаса,
12 строк населения.

### 5.3. Слои 8.3–8.7

```powershell
python -m scripts.load_layers --layer all --dry-run
python -m scripts.load_layers --layer all
```

Можно грузить по одному: `--layer 8.3`, `--layer 8.4`, `--layer 8.5`,
`--layer 8.6`, `--layer 8.7`.

Ожидаемый результат:

| Слой | Что появится |
|---|---|
| 8.3 | 416 программ, 240 расчётных строк |
| 8.4 | 355 договоров, 26 поставщиков, 583 доп. соглашения, 358 лотов |
| 8.5 | 3413 получателей, 21 521 выплата, 46 программ |
| 8.6 | 6165 объектов (1323 ГЧП + 4842 экспертизы), 12 271 участник |
| 8.7 | 3668 организаций, 3668 идентификаторов |

### 5.4. Граф связей

```powershell
python -m scripts.build_relations --dry-run
python -m scripts.build_relations
```

Ожидаемый результат: **11 782 узла, 16 266 связей**.

Граф перестраивается целиком, а не дополняется: связь — производная величина, и
инкрементальное дополнение оставило бы связи, которых в данных больше нет.

### 5.5. Роли, права и учётные записи

```powershell
python -m scripts.seed_access --dry-run
python -m scripts.seed_access
```

Создаются 18 прав, 4 роли и 5 демонстрационных учётных записей.

> **Пароли генерируются и печатаются один раз — при создании учётной записи.**
> В коде их нет и быть не может: одинаковый пароль во всех развёртываниях
> переживает и демонстрацию, и приёмку, и оказывается в проде. Восстановить
> напечатанный пароль позже нельзя — в базе лежит только хеш Argon2id.

Перевыдать пароли: `python -m scripts.seed_access --reset-passwords`.

Существующим записям пароль **не меняется** без явного флага: молчаливая
перевыдача при каждом прогоне выбила бы из системы всех, кто уже работает.

Демонстрационные учётные записи:

| Логин | Роль | Территория | Зачем |
|---|---|---|---|
| `admin` | Администратор | все | Полный доступ |
| `analyst` | Аналитик | Алматинская область | Обычный рабочий сценарий |
| `analyst.karasay` | Аналитик | Карасайский район | Проверка территориального ограничения: Талгарский район недоступен |
| `manager` | Руководитель | все | Просмотр и отчёты |
| `viewer` | Просмотр | Алматинская область | Минимальные права |

### 5.6. Коды возврата загрузчиков

| Код | Смысл |
|---:|---|
| 0 | Успех |
| 1 | Не сошёлся контроль либо есть замечания уровня `ERROR` |
| 2 | Загрузка упала |

Ненулевой код при расхождении контроля нужен, чтобы запуск из планировщика не
считался успешным только потому, что скрипт не упал.

---

## 6. Запуск

### Backend

```powershell
cd <репозиторий>\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Порт 8100 — тот, который фронтенд ожидает по умолчанию.

Проверка:

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health    # {"status":"ok"}
Invoke-RestMethod http://127.0.0.1:8100/ready     # {"status":"ready","checks":{...}}
```

`/health` намеренно не трогает базу; `/ready` проверяет соединение и наличие
PostGIS и отвечает `503`, если база недоступна.

Документация API: `http://127.0.0.1:8100/docs` (Swagger) и `/redoc`.

### Frontend

```powershell
cd <репозиторий>\frontend
npm ci

# разработка
npm run dev            # http://localhost:3000

# продакшн-сборка
npm run build
npm run start          # http://localhost:3000
```

---

## 7. Проверки

```powershell
# backend
cd <репозиторий>\backend
pytest                              # 1115 тестов
mypy app                            # strict, 60 файлов
ruff check app scripts tests        # чисто

# frontend
cd <репозиторий>\frontend
npm run check                       # lint + typecheck + test + contrast
```

`npm run check` разворачивается в
`npm run lint && npm run typecheck && npm run test && npm run check:contrast`.

Отдельные проверки: `npm run test` (218 тестов), `npm run typecheck`
(`tsc --noEmit`), `npm run check:contrast` (44 проверки WCAG 2.1).

Маркеры pytest:

```powershell
pytest -m golden        # сверка с эталонными строками книг
pytest -m integration   # требуется живая база
pytest -m "not slow"    # без чтения больших книг целиком
```

---

## 8. Чего эта конфигурация не даёт

Названо прямо, потому что описанное выше — среда разработки, а не продакшн.

| Что | Состояние | Что нужно для продакшна |
|---|---|---|
| Аутентификация БД | `trust`, без пароля | `scram-sha-256`, отдельная роль приложения с минимальными правами |
| Сеть | loopback только | Настройка `pg_hba.conf`, TLS |
| Служба | ручной `pg_ctl` | Служба Windows либо systemd-юнит |
| Резервное копирование | **нет** | `pg_dump` по расписанию, проверка восстановления |
| HTTPS | нет | Обратный прокси с TLS |
| Секреты | `.env` в файловой системе | Хранилище секретов |
| Токен на клиенте | `localStorage` | `httpOnly`-cookie при развёртывании за общим доменом |
| Мониторинг | логи в файл | Сбор метрик и алертинг |

Кроме того, **PostGIS распространяется под GPL v2+**. Это влияет на условия
распространения производных продуктов, но не на внутреннее использование БД в
проекте.

---

## 9. Если что-то пошло не так

| Симптом | Причина и что делать |
|---|---|
| `postgis_version()` падает | Не наложен бандл PostGIS либо мажорные версии не совпали (`PGSQL="180"` обязателен для PG 18) |
| Ошибки `postgis_raster` | Не заданы `GDAL_DATA` / `PROJ_LIB` **до** запуска `pg_ctl` — переменные наследуются серверным процессом |
| Импорт: «файл не найден», хотя файл на месте | Имя книги в Unicode NFD. Обращение обязано идти через `scripts.source_manifest.resolve_source()`, а не конкатенацией пути |
| `load_territories` останавливается на проверке хеша | Файл границ изменился. Происхождение больше ничего не доказывает — сверьте с `data/boundaries/PROVENANCE.md` |
| Приложение не поднимается под uvicorn, но тесты проходят | Тесты могут не запускать жизненный цикл. Проверьте `/ready` и лог старта |
| Все запросы к API падают из браузера | `localhost` и `127.0.0.1` — разные источники. Проверьте `CORS_ORIGINS` и порт |
| Эндпоинт PDF отвечает `501` | Нет `data/fonts/DejaVuSans.ttf`. Word и Excel при этом работают |
| Отказ старта: `JWT_SECRET обязателен при ENVIRONMENT=prod` | Сгенерируйте секрет (см. § 3) |
| `ruff check .` в `backend/` даёт ошибки | Это каталог `alembic/` с автогенерируемыми миграциями. Проверяйте `ruff check app scripts tests` |
