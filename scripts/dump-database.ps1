# Выгрузка базы в файл для передачи.
#
#     powershell -ExecutionPolicy Bypass -File scripts\dump-database.ps1
#
# ВНИМАНИЕ. Полученный файл содержит ПЕРСОНАЛЬНЫЕ ДАННЫЕ: БИН и ИИН
# 3668 организаций и 3413 получателей субсидий, их наименования и суммы
# выплат. Это не обезличенный набор.
#
# Передавайте его только тем, кто имеет право обрабатывать эти сведения, и
# только по защищённому каналу. Не выкладывайте в публичные репозитории,
# файлообменники и мессенджеры с облачным хранением.
#
# Если получателю достаточно увидеть, как система работает, безопаснее
# передать только код: он поднимется на пустой базе, а данные получатель
# загрузит из своей копии книг. Для этого есть ключ -NoPersonalData.
#
# Файл сохранён в UTF-8 с BOM: PowerShell 5.1 без BOM читает .ps1 как ANSI,
# и кириллица в сообщениях превращается в мусор.

[CmdletBinding()]
param(
    [string]$PgBin = "$env:USERPROFILE\pgsql\bin",
    [int]$Port = 5433,
    [string]$Database = "riskmap",
    [string]$OutputDir = "dist",

    # Не выгружать данные таблиц с персональными сведениями. Схема,
    # справочники и границы сохраняются, поэтому система поднимется.
    [switch]$NoPersonalData
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $repoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$stamp = Get-Date -Format "yyyy-MM-dd"
$suffix = if ($NoPersonalData) { "bez-personalnyh" } else { "polnyy" }
$dumpPath = Join-Path $outDir "riskmap-$stamp-$suffix.dump"

$pgDump = Join-Path $PgBin "pg_dump.exe"
if (-not (Test-Path $pgDump)) { throw "Не найден pg_dump: $pgDump" }

# Таблицы, содержащие идентификаторы физических лиц и организаций.
$personalTables = @(
    "organizations", "persons", "identifiers", "addresses",
    "organization_person_roles", "subsidy_recipients", "subsidy_payments",
    "suppliers", "graph_nodes", "entity_relations"
)

$arguments = @(
    "-U", "postgres", "-p", "$Port", "-d", $Database,
    "--format=custom", "--compress=9", "--no-owner", "--no-privileges",
    "--file", $dumpPath
)

if ($NoPersonalData) {
    Write-Host "Режим без персональных данных: перечисленные таблицы выгружаются пустыми." -ForegroundColor Yellow
    foreach ($table in $personalTables) {
        $arguments += @("--exclude-table-data", "public.$table")
    }
}

Write-Host "Выгрузка базы $Database с порта $Port..." -ForegroundColor Cyan
& $pgDump @arguments
if ($LASTEXITCODE -ne 0) { throw "pg_dump завершился с кодом $LASTEXITCODE" }

$size = (Get-Item $dumpPath).Length
$hash = (Get-FileHash $dumpPath -Algorithm SHA256).Hash
$sizeMb = "{0:N1}" -f ($size / 1MB)

# Описание содержимого собирается до вставки в записку: условная логика
# внутри here-string читается плохо и легко ломается.
if ($NoPersonalData) {
    $contentNote = @"
СОДЕРЖИМОЕ: схема, справочники, территории и границы.
Таблицы с идентификаторами лиц и организаций выгружены ПУСТЫМИ.
Персональных данных в файле нет.
"@
} else {
    $contentNote = @"
СОДЕРЖИМОЕ: полная база, включая ПЕРСОНАЛЬНЫЕ ДАННЫЕ - БИН и ИИН
организаций и получателей субсидий, наименования, суммы выплат.

Передавать только тем, кто имеет право обрабатывать эти сведения,
и только по защищённому каналу. Не выкладывать в публичный доступ.
"@
}

# Рядом с дампом кладём записку о его содержимом. Файл может уехать от
# репозитория, и тогда предупреждение из README до получателя не дойдёт.
$fileName = Split-Path -Leaf $dumpPath
$created = Get-Date -Format "yyyy-MM-dd HH:mm"

$noteText = @"
Дамп базы ИАС «Интерактивная карта рисков»

Файл:      $fileName
Создан:    $created
Размер:    $sizeMb МБ
SHA-256:   $hash
Формат:    pg_dump custom, восстанавливается pg_restore

$contentNote

Восстановление:
    powershell -File scripts\restore-database.ps1 -DumpPath <этот файл>
"@

$notePath = "$dumpPath.txt"
$noteText | Out-File -FilePath $notePath -Encoding utf8

Write-Host "`nГотово." -ForegroundColor Green
Write-Host "  файл:    $dumpPath"
Write-Host "  размер:  $sizeMb МБ"
Write-Host "  SHA-256: $hash"
Write-Host "  записка: $notePath"

if (-not $NoPersonalData) {
    Write-Host "`nВ файле персональные данные. Проверьте, кому и как передаёте." -ForegroundColor Yellow
}
