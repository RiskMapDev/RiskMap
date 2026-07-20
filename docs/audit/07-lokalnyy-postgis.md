# 07. Локальный PostgreSQL + PostGIS без прав администратора

**Статус: УДАЛОСЬ.** Кластер развёрнут, PostGIS работает, связка с Python (psycopg 3) проверена, сервер оставлен запущенным.

Дата развёртывания: **20 июля 2026 г.**
Машина: Windows 11 Home 10.0.26200, PowerShell 5.1, без прав администратора, без Docker, без winget.

---

## 1. Выбранные версии и обоснование

| Компонент | Версия | Почему именно она |
|---|---|---|
| PostgreSQL | **18.4** (x86-64, Windows) | Самая свежая мажорная ветка, для которой EnterpriseDB публикует ZIP-архив бинарников **без инсталлятора** (не требует UAC). |
| PostGIS | **3.6.2** (bundle для pg18) | Единственная актуальная сборка бандла под PG 18; собрана 16 марта 2026 г. |

Мажорные версии совпадают: бандл `postgis-bundle-pg18-*` собран именно под PG 18, расширение сообщает `PGSQL="180"`.

Почему не PG 17: бандл PostGIS 3.6.2 существует и для `pg17`, и для `pg18` (оба выложены 16.03.2026). Выбран PG 18 как более новая ветка с более длинным сроком поддержки. Если по каким-то причинам нужен PG 17 — инструкция ниже воспроизводится один-в-один с заменой `18`→`17` и fileid EDB на `1260307`.

Почему ZIP, а не установщик: установщики EDB и `postgis-bundle-pg18x64-setup-*.exe` требуют UAC и пишут в системные каталоги/реестр. ZIP-вариант распаковывается в домашний каталог пользователя и не требует никаких привилегий.

---

## 2. Источники, лицензии, контрольные суммы

### PostgreSQL 18.4 binaries

- **URL:** `https://sbp.enterprisedb.com/getfile.jsp?fileid=1260303`
- Страница-каталог: <https://www.enterprisedb.com/download-postgresql-binaries>
- Скачано: 20.07.2026
- Имя локального файла: `pg18-binaries.zip`
- Размер: **337 445 815 байт** (321,8 МиБ)
- **SHA-256:** `02E239529ED7833D169F98D915D3FEFFE0813264B08B3AE353E78E8B9C97E1A6`
- Лицензия: **PostgreSQL License** (BSD/MIT-подобная, разрешает коммерческое использование). Текст лежит в архиве: `pgsql/server_license.txt`. Сторонние компоненты сборки EDB — `pgsql/commandlinetools_3rd_party_licenses.txt`, `pgsql/pgAdmin_license.txt`.
- ⚠️ EnterpriseDB **не публикует** контрольные суммы для этих ZIP — сверить было не с чем. SHA-256 выше зафиксирован постфактум для воспроизводимости: если вы скачаете тот же файл и получите другой хеш, файл изменился.

### PostGIS 3.6.2 bundle (pg18)

- **URL:** `https://download.osgeo.org/postgis/windows/pg18/postgis-bundle-pg18-3.6.2x64.zip`
- Файл контрольной суммы: `https://download.osgeo.org/postgis/windows/pg18/postgis-bundle-pg18-3.6.2x64.zip.md5`
- Скачано: 20.07.2026 (файл на сервере от 2026-Mar-16 07:57)
- Размер: **124 037 332 байта** (118,3 МиБ)
- **SHA-256:** `0F41241CC536F7404DDA43FD2A3F20FFE1FA1D71A8D4F6341428CD25931BF419`
- **MD5 (опубликован издателем):** `9e28723541938d1b1a8efb59a5922741` — ✅ **совпал** с фактическим.
- Лицензия: **GNU GPL v2 или новее**. Текст в архиве: `LICENSE`. Внутри бандла есть компоненты с собственными лицензиями (pgRouting — GPLv2, pgPointCloud, MobilityDB, ogr_fdw, pg_sphere, h3-pg — см. соответствующие `*_LICENSE`/`COPYRIGHT` файлы).

> Замечание по лицензированию: PostGIS распространяется под GPL. Это влияет на условия распространения производных продуктов, но не на внутреннее использование БД в проекте.

---

## 3. Полная последовательность команд PowerShell

Все команды выполняются в обычном (не повышенном) PowerShell. Ничего не пишется в `C:\Program Files`, `C:\Windows` или реестр.

### 3.1. Скачивание

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

### 3.2. Проверка контрольных сумм

```powershell
# MD5 PostGIS — должен совпасть с содержимым .md5-файла
Get-Content "$sp\postgis-bundle-pg18-3.6.2x64.zip.md5"
(Get-FileHash "$sp\postgis-bundle-pg18-3.6.2x64.zip" -Algorithm MD5).Hash

# SHA-256 обоих архивов — сверить со значениями из раздела 2
(Get-FileHash "$sp\postgis-bundle-pg18-3.6.2x64.zip" -Algorithm SHA256).Hash
(Get-FileHash "$sp\pg18-binaries.zip"                -Algorithm SHA256).Hash
```

### 3.3. Распаковка

Архив PostgreSQL содержит корневую папку `pgsql/`, поэтому распаковываем в `C:\Users\erbot`, чтобы получить `C:\Users\erbot\pgsql`.

```powershell
Expand-Archive -Path "$sp\pg18-binaries.zip" -DestinationPath "C:\Users\erbot" -Force

# Бандл PostGIS распаковываем во временную папку...
Expand-Archive -Path "$sp\postgis-bundle-pg18-3.6.2x64.zip" -DestinationPath "$sp\pgis" -Force

# ...и накладываем его содержимое (bin/ lib/ share/ gdal-data/ ...) поверх дерева PostgreSQL
Copy-Item -Path "$sp\pgis\postgis-bundle-pg18-3.6.2x64\*" `
          -Destination "C:\Users\erbot\pgsql" -Recurse -Force

# Проверка
& "C:\Users\erbot\pgsql\bin\postgres.exe" --version
# -> postgres (PostgreSQL) 18.4
Get-ChildItem "C:\Users\erbot\pgsql\share\extension\postgis*.control"
```

### 3.4. Инициализация кластера

```powershell
& "C:\Users\erbot\pgsql\bin\initdb.exe" `
    -D "C:\Users\erbot\pgsql\data" `
    -U postgres --encoding=UTF8 --locale=C --auth=trust
```

`--auth=trust` — локальный dev-кластер, слушает только loopback, пароль не требуется. **Для чего-либо кроме локальной разработки так делать нельзя.**

### 3.5. Запуск сервера на порту 5433

Переменные `GDAL_DATA` и `PROJ_LIB` задаются **до** запуска — серверный процесс наследует их от `pg_ctl`. Без них не работает часть функционала `postgis_raster` (см. раздел 7).

```powershell
$env:GDAL_DATA = "C:\Users\erbot\pgsql\gdal-data"
$env:PROJ_LIB  = "C:\Users\erbot\pgsql\share\contrib\postgis-3.6\proj"

& "C:\Users\erbot\pgsql\bin\pg_ctl.exe" `
    -D "C:\Users\erbot\pgsql\data" `
    -l "C:\Users\erbot\pgsql\logfile.txt" `
    -o "-p 5433 -c listen_addresses=127.0.0.1" start
```

Порт 5433 выбран нестандартным, чтобы не конфликтовать с возможной будущей штатной установкой PostgreSQL на 5432.

### 3.6. Создание БД и расширения

```powershell
$env:PGHOST = "127.0.0.1"; $env:PGPORT = "5433"; $env:PGUSER = "postgres"

& "C:\Users\erbot\pgsql\bin\createdb.exe" riskmap
& "C:\Users\erbot\pgsql\bin\psql.exe" -d riskmap -c "CREATE EXTENSION postgis;"
& "C:\Users\erbot\pgsql\bin\psql.exe" -d riskmap -A -t -c "SELECT postgis_full_version();"
```

---

## 4. Параметры подключения

| Параметр | Значение |
|---|---|
| host | `127.0.0.1` |
| port | **5433** |
| database | `riskmap` |
| user | `postgres` |
| password | не требуется (`trust`-аутентификация) |
| кодировка | UTF8, локаль `C` |

Строки подключения:

```
postgresql://postgres@127.0.0.1:5433/riskmap
```

```python
DSN = "host=127.0.0.1 port=5433 dbname=riskmap user=postgres"
```

Служебная БД `postgres` доступна на тех же параметрах.

---

## 5. Результат проверки

### `SELECT postgis_full_version();`

```
POSTGIS="3.6.2 3.6.2" [EXTENSION] PGSQL="180"
GEOS="3.14.1dev-CAPI-1.20.4"
PROJ="8.2.1 NETWORK_ENABLED=OFF URL_ENDPOINT=https://cdn.proj.org
      USER_WRITABLE_DIRECTORY=C:\Users\erbot\AppData\Local/proj
      DATABASE_PATH=C:\Users\erbot\pgsql\share\contrib\postgis-3.6\proj\proj.db"
      (compiled against PROJ 8.2.1)
LIBXML="2.12.5" LIBJSON="0.12" LIBPROTOBUF="1.2.1" WAGYU="0.5.0 (Internal)"
```

### `SELECT version();`

```
PostgreSQL 18.4 on x86_64-windows, compiled by msvc-19.44.35227, 64-bit
```

### `SELECT postgis_gdal_version();`

```
GDAL 3.9.2, released 2024/08/13
```

### Проверка из Python (psycopg 3.3.4, Python 3.14.0)

Скрипт подключается, создаёт таблицу с типизированной геометрией и GiST-индексом и выполняет пространственные запросы. Фактический вывод:

```
ST_Area(2x2 deg square)   = 4.0
Geodesic area m^2         = 69914139.95401764
Transform 4326->3857      = POINT(4187538.6810178095 7509955.142338095)
ST_Contains(Moscow center)= ('test-zone', True)
geometry_columns          = [('zones', 'POLYGON', 4326)]
OK: psycopg + PostGIS round-trip succeeded
```

Проверено дополнительно:
- перепроекция, требующая обращения к `proj.db`: `EPSG:4326 → EPSG:3035` вернула `POINT(4253861.399545367 3321736.463013416)`;
- `postgis_raster`: `ST_MakeEmptyRaster` + `ST_AddBand` → растр 10×10 создаётся корректно;
- `postgis_topology` устанавливается без ошибок.

Расширения `postgis_raster` и `postgis_topology` после проверки были удалены — в БД `riskmap` установлено только базовое `postgis`.

---

## 6. Управление сервером

### Запуск

```powershell
$env:GDAL_DATA = "C:\Users\erbot\pgsql\gdal-data"
$env:PROJ_LIB  = "C:\Users\erbot\pgsql\share\contrib\postgis-3.6\proj"
& "C:\Users\erbot\pgsql\bin\pg_ctl.exe" -D "C:\Users\erbot\pgsql\data" `
    -l "C:\Users\erbot\pgsql\logfile.txt" -o "-p 5433 -c listen_addresses=127.0.0.1" start
```

### Статус

```powershell
& "C:\Users\erbot\pgsql\bin\pg_ctl.exe" -D "C:\Users\erbot\pgsql\data" status
```

### Остановка

```powershell
& "C:\Users\erbot\pgsql\bin\pg_ctl.exe" -D "C:\Users\erbot\pgsql\data" stop
```

Аварийная остановка (обрыв всех соединений): добавить `-m immediate`.

### Перезапуск

```powershell
& "C:\Users\erbot\pgsql\bin\pg_ctl.exe" -D "C:\Users\erbot\pgsql\data" `
    -l "C:\Users\erbot\pgsql\logfile.txt" -o "-p 5433 -c listen_addresses=127.0.0.1" restart
```

### Лог

```powershell
Get-Content "C:\Users\erbot\pgsql\logfile.txt" -Tail 50
```

### Удобный шорткат для сессии

```powershell
$env:Path     = "C:\Users\erbot\pgsql\bin;$env:Path"
$env:PGHOST   = "127.0.0.1"
$env:PGPORT   = "5433"
$env:PGUSER   = "postgres"
$env:PGDATABASE = "riskmap"
psql            # подключится сразу к riskmap
```

---

## 7. Известные ограничения и подводные камни

1. **Сервер не запускается автоматически.** Это не служба Windows (регистрация службы через `pg_ctl register` требует прав администратора). После перезагрузки машины кластер нужно поднимать вручную командой из раздела 6. Если нужен автозапуск без UAC — можно положить `.cmd`-обёртку в папку автозагрузки пользователя (`shell:startup`); в реестр при этом лезть не нужно.

2. **`GDAL_DATA` / `PROJ_LIB` надо задавать перед каждым запуском.** Серверный процесс наследует окружение от `pg_ctl`. Если запустить сервер без этих переменных, `postgis_gdal_version()` вернёт `GDAL_DATA not found`, и часть операций `postgis_raster` (работа с системами координат в растрах, `ST_Transform` растров, импорт GeoTIFF) будет вести себя некорректно. Векторный PostGIS при этом работает. Сделать переменные постоянными можно через `[Environment]::SetEnvironmentVariable(..., 'User')`, но это запись в пользовательскую ветку реестра — в данной установке намеренно не делалось.

3. **`trust`-аутентификация.** Любой процесс на этой машине может подключиться к кластеру как `postgres` без пароля. Приемлемо только потому, что сервер слушает исключительно `127.0.0.1`. Перед любым выходом за пределы локальной разработки нужно задать пароль (`ALTER USER postgres PASSWORD '...'`) и сменить метод в `C:\Users\erbot\pgsql\data\pg_hba.conf` на `scram-sha-256`.

4. **Локаль `C`.** Сортировка строк — побайтовая, не языковая. Для русских текстов `ORDER BY` даст не алфавитный порядок. Если это станет важно, нужно либо пересоздать кластер с другой локалью, либо использовать `COLLATE` на уровне колонок/запросов (в PG 18 доступен встроенный провайдер `builtin` с локалью `C.UTF-8`).

5. **PROJ 8.2.1 — довольно старая версия** в составе бандла (актуальные PROJ — 9.x). Сетевые загрузки грид-файлов отключены (`NETWORK_ENABLED=OFF`), доступны только те трансформации, чьи гриды лежат в `share\contrib\postgis-3.6\proj`. Для большинства задач (WGS84 ↔ Web Mercator ↔ UTM ↔ национальные проекции) этого достаточно, но высокоточные датум-сдвиги для некоторых регионов могут быть недоступны.

6. **Занимаемое место:** ~1,2 ГБ в `C:\Users\erbot\pgsql` (включая pgAdmin 4 и StackBuilder из архива EDB, которые не используются и могут быть удалены для экономии ~500 МБ).

7. **EDB не публикует контрольные суммы** для ZIP-архивов бинарников. Целостность подтверждается только HTTPS-каналом. Для PostGIS официальный MD5 есть и совпал.

8. **Кластер принадлежит текущему пользователю Windows.** `initdb` сообщил владельца как пользователя `Y` (короткое имя учётной записи). Запускать сервер под другой учётной записью нельзя без смены прав на каталог `data`.

9. **Расширения сверх PostGIS.** Бандл дополнительно содержит готовые к установке `pgrouting 4.0.1`, `postgis_raster`, `postgis_topology`, `postgis_sfcgal`, `postgis_tiger_geocoder`, `address_standardizer`, `pointcloud 1.2.5`, `ogr_fdw 1.1`, `mobilitydb 1.3.0`, `pg_sphere 1.5.2`, `h3 4.1.4`. Ставятся обычным `CREATE EXTENSION <имя>;`.

---

## 8. Что делать, если воспроизвести не удалось (fallback)

Здесь не понадобилось — установка прошла без ошибок с первой попытки. На случай проблем на другой машине:

- **Если EDB-ссылка отдаёт 404/редирект:** `fileid` в `sbp.enterprisedb.com/getfile.jsp?fileid=...` меняются при выходе новых минорных версий. Актуальный список всегда на <https://www.enterprisedb.com/download-postgresql-binaries>.
- **Если нет подходящего бандла PostGIS под выбранный PG:** спуститься на мажорную версию ниже (каталоги `pg17`, `pg16` на <https://download.osgeo.org/postgis/windows/>).
- **Если запуск полноценного сервера невозможен в принципе** (жёсткие политики блокировки исполняемых файлов вне системных каталогов, AppLocker): резервный вариант — **SQLite + SpatiaLite** (`mod_spatialite` подключается как расширение через `sqlite3`, ставится из pip-пакета или распаковкой DLL). Он покрывает базовую геометрию, GEOS-предикаты и PROJ-перепроекции, но не даёт серверной модели, конкурентного доступа, растров PostGIS и pgRouting.
