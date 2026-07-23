@echo off
rem Запуск всей системы одной командой. Нужен только Docker Desktop.
rem Что делает: создаёт .env с секретом, поднимает контейнеры, при первом
rem запуске восстанавливает базу из дампа в dist\, открывает браузер.
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker не найден. Установите Docker Desktop: https://www.docker.com/products/docker-desktop/
    pause
    exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
    echo Docker установлен, но не запущен. Откройте Docker Desktop и повторите.
    pause
    exit /b 1
)

if not exist .env (
    echo Создаю .env со свежим секретом...
    powershell -NoProfile -Command "$s=-join(((48..57)+(65..90)+(97..122))*2|Get-Random -Count 48|ForEach-Object{[char]$_}); Set-Content .env \"JWT_SECRET=$s\" -Encoding ascii"
)

echo Сборка и запуск контейнеров — первый раз занимает несколько минут...
docker compose up -d --build
if errorlevel 1 (
    echo Не удалось поднять контейнеры. Текст ошибки выше.
    pause
    exit /b 1
)

echo Жду готовности базы...
set tries=0
:waitdb
docker compose exec db pg_isready -U postgres -d riskmap >nul 2>nul
if errorlevel 1 (
    set /a tries+=1
    if !tries! geq 60 (
        echo База не поднялась за 2 минуты. Смотрите: docker compose logs db
        pause
        exit /b 1
    )
    timeout /t 2 /nobreak >nul
    goto waitdb
)

rem Данные уже загружены? Проверяем по таблице территорий.
for /f %%c in ('docker compose exec db psql -U postgres -d riskmap -tAc "select count(*) from pg_stat_user_tables where relname='territories'"') do set hasdata=%%c

if "!hasdata!"=="0" (
    set dump=
    for %%f in (dist\riskmap-*-polnyy.dump) do set dump=%%f
    if "!dump!"=="" (
        echo Дамп базы не найден в dist\ — система поднимется пустой.
    ) else (
        echo Восстанавливаю базу из !dump! — около минуты...
        docker compose cp "!dump!" db:/tmp/riskmap.dump
        docker compose exec db pg_restore -U postgres -d riskmap --no-owner --no-privileges --single-transaction --exit-on-error /tmp/riskmap.dump
        if errorlevel 1 (
            echo Восстановление не удалось. Смотрите текст ошибки выше.
            pause
            exit /b 1
        )
    )
) else (
    echo База уже наполнена — восстановление пропущено.
)

echo.
echo Готово. Интерфейс: http://localhost:3000  ^(вход: admin / 123123123123^)
echo Остановить: docker compose down
start http://localhost:3000
endlocal
