"""Точка входа FastAPI."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.auth_routes import router as auth_router
from app.core.config import Settings, get_settings
from app.db.session import get_engine

logger = logging.getLogger("riskmap")

REQUEST_ID_HEADER = "X-Request-ID"


def _database_host(settings: Settings) -> str:
    """Хост базы для стартовой записи в лог.

    `PostgresDsn` в pydantic 2 многохостовый, и атрибута `.host` у него нет —
    обращение к нему роняло запуск приложения целиком, потому что это первое,
    что делает lifespan. Пароль сюда не попадает: в лог уходит только хост и
    порт, а не строка подключения.
    """
    hosts = settings.database_url.hosts()
    if not hosts:
        return "не указан"
    first = hosts[0]
    return f"{first.get('host') or '?'}:{first.get('port') or '?'}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "Запуск в режиме %s, БД %s",
        settings.environment,
        _database_host(settings),
    )
    yield
    get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ИАС «Интерактивная карта рисков»",
        description=(
            "Информационно-аналитическая система оценки социально-экономических "
            "и криминогенных рисков в регионе."
        ),
        version="0.1.0",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Сквозной идентификатор запроса и замер длительности.

        ТЗ задаёт нормативы времени отклика, поэтому длительность пишется в лог
        всегда, а не только при отладке: иначе нечем подтвердить соблюдение.
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s → %s за %.0f мс",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra={"request_id": request_id, "duration_ms": elapsed_ms},
        )
        return response

    from app.api.territory_routes import router as territory_router

    app.include_router(territory_router, prefix=settings.api_prefix)

    # Маршруты доступа. Префикс версии задан настройкой: ломающие изменения API
    # должны выражаться сменой версии, а не правкой путей по месту.
    app.include_router(auth_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["служебные"], summary="Живо ли приложение")
    def health() -> dict[str, str]:
        """Проверка живости процесса. Базу намеренно не трогает."""
        return {"status": "ok"}

    @app.get("/ready", tags=["служебные"], summary="Готово ли к работе")
    def ready() -> JSONResponse:
        """Готовность: доступна ли БД и включён ли PostGIS.

        Отдельно от `/health`: приложение может быть живым, но неспособным
        обслуживать запросы. Смешивать эти состояния — значит получать
        перезапуски там, где нужно просто дождаться базы.
        """
        checks: dict[str, str] = {}
        ok = True

        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
                checks["database"] = "ok"
                version = conn.execute(text("select postgis_version()")).scalar_one()
                checks["postgis"] = str(version)
        except Exception as exc:
            ok = False
            checks["database"] = "недоступна"
            logger.exception("Проверка готовности не прошла: %s", exc)

        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ready" if ok else "not ready", "checks": checks},
        )

    return app


app = create_app()
