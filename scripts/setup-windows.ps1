# Установка без Docker и без прав администратора.
#
#     powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
#
# Что делает: разворачивает PostgreSQL с PostGIS из ZIP-бинарников в
# пользовательский каталог, создаёт базу, применяет миграции, заводит роли и
# демонстрационные учётные записи.
#
# Почему именно так. Установщик PostgreSQL требует прав администратора и
# записывает в реестр; ZIP-бинарники не требуют ни того ни другого, и вся
# установка живёт в одном каталоге, который можно удалить одной командой.
# Этот путь проверен запуском, в отличие от docker-compose.
#
# Ничего не удаляет за пределами своего каталога и не трогает системные
# настройки. Повторный запуск не ломает уже установленное.

[CmdletBinding()]
param(
    # Куда положить сервер базы. По умолчанию — домашний каталог пользователя.
    [string]$PgRoot = "$env:USERPROFILE\pgsql",

    # Порт намеренно нестандартный: 5432 может быть занят другой установкой,
    # и молча подключиться не к той базе — худшее, что может случиться.
    [int]$Port = 5433,

    [string]$Database = "riskmap",

    # Пропустить установку сервера, если PostgreSQL уже развёрнут.
    [switch]$SkipServer,

    # Не заводить демонстрационные учётные записи.
    [switch]$SkipSeed
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  $text" -ForegroundColor Yellow }

# --- Проверка окружения ------------------------------------------------------

Step "Проверка окружения"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw "Не найден python. Установите Python 3.12 или новее." }
$pyVersion = (& python --version 2>&1) -replace 'Python\s+', ''
Ok "python $pyVersion"

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { throw "Не найден node. Установите Node.js 20 или новее." }
Ok "node $(& node --version)"

# --- Сервер базы -------------------------------------------------------------

$pgBin = Join-Path $PgRoot "bin"
$pgData = Join-Path $PgRoot "data"

if ($SkipServer) {
    Step "Установка сервера пропущена"
} elseif (Test-Path (Join-Path $pgBin "pg_ctl.exe")) {
    Step "Сервер базы уже развёрнут"
    Ok $PgRoot
} else {
    Step "Установка PostgreSQL и PostGIS"
    Warn "Сервер и расширение занимают около 1,2 ГБ и качаются из сети."
    Warn "Точные ссылки и контрольные суммы — в docs/deployment.md."
    throw @"
Автоматическая загрузка не выполняется намеренно: ссылки EnterpriseDB
меняются, а тихо скачать не тот файл хуже, чем остановиться.

Выполните разово по инструкции docs/deployment.md, раздел
«Установка PostGIS без прав администратора», затем запустите этот скрипт
повторно с уже распакованным сервером.

Либо, если Docker доступен, воспользуйтесь docker compose — это проще.
"@
}

# --- Кластер -----------------------------------------------------------------

if (-not $SkipServer) {
    if (-not (Test-Path (Join-Path $pgData "PG_VERSION"))) {
        Step "Создание кластера"
        & (Join-Path $pgBin "initdb.exe") -D $pgData -U postgres --encoding=UTF8 --locale=C --auth=trust | Out-Null
        Ok "кластер создан в $pgData"
    } else {
        Ok "кластер уже существует"
    }

    # GDAL и PROJ нужны PostGIS для репроекции. Без них расширение
    # устанавливается, но преобразование координат падает — а обнаруживается
    # это далеко не сразу.
    $env:GDAL_DATA = Join-Path $PgRoot "gdal-data"
    $env:PROJ_LIB = Join-Path $PgRoot "share\contrib\postgis-3.6\proj"

    $status = & (Join-Path $pgBin "pg_ctl.exe") -D $pgData status 2>&1
    if ($LASTEXITCODE -ne 0) {
        Step "Запуск сервера"
        & (Join-Path $pgBin "pg_ctl.exe") -D $pgData -l (Join-Path $PgRoot "logfile.txt") `
            -o "-p $Port -c listen_addresses=127.0.0.1" start | Out-Null
        Start-Sleep -Seconds 3
        Ok "сервер слушает 127.0.0.1:$Port"
    } else {
        Ok "сервер уже запущен"
    }

    # --- База и расширение ---------------------------------------------------

    Step "База данных"
    $exists = & (Join-Path $pgBin "psql.exe") -U postgres -p $Port -d postgres -tAc `
        "select 1 from pg_database where datname='$Database'" 2>$null
    if ($exists -ne "1") {
        & (Join-Path $pgBin "createdb.exe") -U postgres -p $Port $Database
        Ok "база $Database создана"
    } else {
        Ok "база $Database уже существует"
    }

    & (Join-Path $pgBin "psql.exe") -U postgres -p $Port -d $Database -c "CREATE EXTENSION IF NOT EXISTS postgis" | Out-Null
    $postgis = & (Join-Path $pgBin "psql.exe") -U postgres -p $Port -d $Database -tAc "select postgis_version()"
    Ok "PostGIS $postgis"
}

# --- Настройки приложения ----------------------------------------------------

Step "Файл настроек"

$envPath = Join-Path $repoRoot ".env"
if (Test-Path $envPath) {
    Ok ".env уже есть, не трогаю"
} else {
    $secret = & python -c "import secrets; print(secrets.token_urlsafe(48))"
    @"
ENVIRONMENT=dev
DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:$Port/$Database
JWT_SECRET=$secret
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001
NEXT_PUBLIC_API_URL=http://127.0.0.1:8100/api/v1
"@ | Out-File -FilePath $envPath -Encoding utf8
    Ok ".env создан, секрет сгенерирован"
}

# --- Зависимости -------------------------------------------------------------

Step "Зависимости backend"
Push-Location (Join-Path $repoRoot "backend")
try {
    & python -m pip install --quiet -e ".[dev]"
    Ok "установлены"
} finally { Pop-Location }

Step "Зависимости frontend"
Push-Location (Join-Path $repoRoot "frontend")
try {
    & npm ci --silent
    Ok "установлены"
} finally { Pop-Location }

# --- Схема и учётные записи --------------------------------------------------

Step "Миграции"
Push-Location (Join-Path $repoRoot "backend")
try {
    & python -m alembic upgrade head
    Ok "схема применена"

    if (-not $SkipSeed) {
        Step "Роли, права и демонстрационные учётные записи"
        & python -m scripts.seed_access
    }
} finally { Pop-Location }

# --- Что дальше --------------------------------------------------------------

Step "Готово"

Write-Host @"

База поднята и схема применена, но данных в ней пока нет.

Дальше одно из двух:

  1. Восстановить дамп, если он вам передан:
       powershell -File scripts\restore-database.ps1 -DumpPath <файл.dump>

  2. Загрузить из книг комплекта ДЭР:
       # укажите путь к книгам в .env через SOURCE_DATA_DIR
       cd backend
       python -m scripts.load_territories
       python -m scripts.load_layers --layer all
       python -m scripts.build_relations

Запуск:
       cd backend  ; python -m uvicorn app.main:app --port 8100
       cd frontend ; npm run build ; npx next start -p 3001

Интерфейс: http://127.0.0.1:3001
API и схема: http://127.0.0.1:8100/docs

"@ -ForegroundColor White
