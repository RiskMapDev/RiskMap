FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --silent
COPY . .
RUN npm run build

# Собранную статику раздаёт отдельный сервис nginx (см. docker-compose.yml):
# этот контейнер только выкладывает build в общий том и завершается.
FROM alpine:3.20
COPY --from=builder /app/build /build
CMD ["sh", "-c", "rm -rf /out/* && cp -r /build/. /out/ && echo 'frontend build -> volume: ok'"]
