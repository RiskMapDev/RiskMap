# Образ frontend.
#
# Сборка в два этапа: в готовый образ не должны попадать ни исходники, ни
# зависимости для сборки. Next кладёт всё необходимое в `standalone`, и
# итоговый образ получается в разы меньше.

FROM node:22-slim AS builder

WORKDIR /app

# Зависимости отдельным слоем — он переиспользуется, пока не менялся
# package-lock.json.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Адрес API попадает в клиентский код на этапе сборки: переменные с
# префиксом NEXT_PUBLIC_ подставляются компилятором, а не читаются в
# рантайме. Значит, при смене адреса образ нужно пересобрать.
ARG NEXT_PUBLIC_API_URL=http://127.0.0.1:8100/api/v1
ARG NEXT_PUBLIC_MAP_STYLE_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_MAP_STYLE_URL=$NEXT_PUBLIC_MAP_STYLE_URL

RUN npm run build


FROM node:22-slim AS runner

WORKDIR /app
ENV NODE_ENV=production

# `standalone` содержит серверную часть и только нужные модули; статику и
# public копируем рядом, как того требует этот режим сборки.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

RUN useradd --create-home --uid 10002 riskmap && chown -R riskmap:riskmap /app
USER riskmap

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
