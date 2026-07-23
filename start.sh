#!/usr/bin/env bash
# Запуск всей системы одной командой (Mac/Linux). Нужен только Docker.
# Что делает: создаёт .env с секретом, поднимает контейнеры, при первом
# запуске восстанавливает базу из дампа в dist/, печатает адрес.
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker не найден: https://docs.docker.com/get-docker/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker установлен, но не запущен."; exit 1; }

if [ ! -f .env ]; then
    echo "Создаю .env со свежим секретом..."
    echo "JWT_SECRET=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 48)" > .env
fi

echo "Сборка и запуск контейнеров — первый раз занимает несколько минут..."
docker compose up -d --build

echo "Жду готовности базы..."
for _ in $(seq 60); do
    docker compose exec db pg_isready -U postgres -d riskmap >/dev/null 2>&1 && break
    sleep 2
done

hasdata=$(docker compose exec db psql -U postgres -d riskmap -tAc \
    "select count(*) from pg_stat_user_tables where relname='territories'" | tr -d '[:space:]')

if [ "$hasdata" = "0" ]; then
    dump=$(ls dist/riskmap-*-polnyy.dump 2>/dev/null | tail -1 || true)
    if [ -z "$dump" ]; then
        echo "Дамп базы не найден в dist/ — система поднимется пустой."
    else
        echo "Восстанавливаю базу из $dump — около минуты..."
        docker compose cp "$dump" db:/tmp/riskmap.dump
        docker compose exec db pg_restore -U postgres -d riskmap \
            --no-owner --no-privileges --single-transaction --exit-on-error /tmp/riskmap.dump
    fi
else
    echo "База уже наполнена — восстановление пропущено."
fi

echo
echo "Готово. Интерфейс: http://localhost:3000  (вход: admin / 123123123123)"
echo "Остановить: docker compose down"
