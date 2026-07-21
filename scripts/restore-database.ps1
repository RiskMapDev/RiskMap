# Восстановление базы из дампа.
#
#     powershell -ExecutionPolicy Bypass -File scripts\restore-database.ps1 -DumpPath dist\riskmap-....dump
#
# Скрипт восстанавливает в СУЩЕСТВУЮЩУЮ базу и по умолчанию отказывается
# работать, если в ней уже есть данные: молча затереть чужую базу — не то,
# чего ждут от команды восстановления. Для перезаписи есть явный ключ.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DumpPath,

    [string]$PgBin = "$env:USERPROFILE\pgsql\bin",
    [int]$Port = 5433,
    [string]$Database = "riskmap",

    # Затереть содержимое базы перед восстановлением.
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $DumpPath)) { throw "Файл дампа не найден: $DumpPath" }

$pgRestore = Join-Path $PgBin "pg_restore.exe"
$psql = Join-Path $PgBin "psql.exe"
if (-not (Test-Path $pgRestore)) { throw "Не найден pg_restore: $pgRestore" }

# Сверка контрольной суммы, если рядом лежит записка от dump-database.ps1.
$notePath = "$DumpPath.txt"
if (Test-Path $notePath) {
    $expected = (Select-String -Path $notePath -Pattern "SHA-256:\s*([0-9A-Fa-f]{64})").Matches.Groups[1].Value
    if ($expected) {
        $actual = (Get-FileHash $DumpPath -Algorithm SHA256).Hash
        if ($actual -ne $expected) {
            throw @"
Контрольная сумма не совпала — файл повреждён или подменён.
  ожидалось: $expected
  получено:  $actual
"@
        }
        Write-Host "Контрольная сумма совпала." -ForegroundColor Green
    }
}

# Проверка, не затираем ли чужие данные.
#
# `spatial_ref_sys` исключена намеренно: PostGIS заводит в ней около 8500
# систем координат при создании расширения. Без этого исключения проверка
# срабатывала бы на любой, даже совершенно пустой базе, требовала бы -Force
# каждый раз и очень быстро перестала бы кого-либо останавливать.
$existing = & $psql -U postgres -p $Port -d $Database -tAc @"
select coalesce(sum(n_live_tup), 0) from pg_stat_user_tables
where relname not in ('spatial_ref_sys')
"@ 2>$null

if ($existing -and [int]$existing -gt 0 -and -not $Force) {
    throw @"
В базе $Database уже есть данные (строк: $existing).

Восстановление затрёт их. Если это осознанное решение, повторите с ключом:
    powershell -File scripts\restore-database.ps1 -DumpPath "$DumpPath" -Force
"@
}

if ($Force -and $existing -and [int]$existing -gt 0) {
    Write-Host "Очистка схемы public…" -ForegroundColor Yellow
    & $psql -U postgres -p $Port -d $Database -c "drop schema public cascade; create schema public;" | Out-Null
    & $psql -U postgres -p $Port -d $Database -c "create extension if not exists postgis;" | Out-Null
}

Write-Host "Восстановление в базу $Database на порту $Port…" -ForegroundColor Cyan

# `--no-owner` и `--no-privileges`: у получателя другие роли, и попытка
# назначить владельца, которого нет, прервала бы восстановление.
# `--single-transaction` — чтобы при ошибке не осталось половины базы.
& $pgRestore -U postgres -p $Port -d $Database `
    --no-owner --no-privileges --single-transaction --exit-on-error $DumpPath

if ($LASTEXITCODE -ne 0) { throw "pg_restore завершился с кодом $LASTEXITCODE" }

Write-Host "`nПроверка содержимого:" -ForegroundColor Cyan
$checks = @(
    @{ Label = "территории"; Query = "select count(*) from territories" },
    @{ Label = "договоры"; Query = "select count(*) from contracts" },
    @{ Label = "получатели субсидий"; Query = "select count(*) from subsidy_recipients" },
    @{ Label = "объекты 8.6"; Query = "select count(*) from project_entities" },
    @{ Label = "организации"; Query = "select count(*) from organizations" },
    @{ Label = "связи графа"; Query = "select count(*) from entity_relations" }
)

foreach ($check in $checks) {
    $value = & $psql -U postgres -p $Port -d $Database -tAc $check.Query 2>$null
    "{0,-22} {1}" -f $check.Label, $value.Trim() | Write-Host
}

Write-Host "`nГотово. Учётные записи в дамп входят — пароли те же, что были у отправителя." -ForegroundColor Green
Write-Host "Смените их: cd backend ; python -m scripts.seed_access --reset-passwords" -ForegroundColor Yellow
