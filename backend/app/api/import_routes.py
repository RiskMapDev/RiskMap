"""Эндпоинты мастера импорта.

Мастер трёхшаговый, и эндпоинты повторяют его шаги, а не устройство базы:
`upload` → `dry-run` → `confirm`. Промежуточное состояние между шагами не
хранится в памяти процесса — шаг 2 возвращает всё, что нужно шагу 3, а сам
файл лежит в каталоге загрузок под именем-хешем. Так мастер переживает
перезапуск приложения и работает за балансировщиком, где следующий запрос
попадает на другой процесс.

Права разведены намеренно. `data.import` даёт право загружать и подтверждать,
`data.import.rollback` — отзывать версию. Это разные полномочия: ошибиться при
загрузке может каждый, а отозвать уже опубликованную версию — решение с иными
последствиями (см. `app/core/permissions.py`).

Клиент здесь не источник истины ни в чём: тип данных, сопоставление и размер
файла проверяются сервером заново, независимо от того, что показал интерфейс.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.api.deps import DbSession, RequestCtx
from app.core.config import get_settings
from app.core.permissions import PermissionCode, require_permission
from app.db.models.access import User
from app.db.models.source import ImportJob
from app.services import import_wizard
from app.services.import_wizard import DataKind, ImportWizardError

router = APIRouter(prefix="/imports", tags=["импорт"])

#: Загрузка и подтверждение.
_REQUIRE_IMPORT = Depends(require_permission(PermissionCode.DATA_IMPORT))

#: Отзыв версии — отдельное право, см. docstring модуля.
_REQUIRE_ROLLBACK = Depends(require_permission(PermissionCode.DATA_IMPORT_ROLLBACK))

ImportUser = Annotated[User, _REQUIRE_IMPORT]
RollbackUser = Annotated[User, _REQUIRE_ROLLBACK]


def _fail(error: ImportWizardError) -> HTTPException:
    """Перевести отказ мастера в код ответа.

    Коды разведены не ради красоты: 413 и 415 браузер и прокси обрабатывают
    иначе, чем общий 400, а интерфейсу нужно различать «файл великоват» и
    «в файле не то» — подсказки у них противоположные.
    """
    codes = {
        # Числовой код, а не константа Starlette: имя константы меняется между
        # версиями (413 переименован в CONTENT_TOO_LARGE), а само число — нет.
        "file_too_large": 413,
        "unsupported_format": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "legacy_xls": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        "upload_not_found": status.HTTP_404_NOT_FOUND,
        "job_not_found": status.HTTP_404_NOT_FOUND,
        "already_rolled_back": status.HTTP_409_CONFLICT,
        "dry_run_rollback": status.HTTP_409_CONFLICT,
    }
    return HTTPException(
        status_code=codes.get(error.code, status.HTTP_400_BAD_REQUEST),
        detail={"code": error.code, "message": error.message},
    )


class MappingBody(BaseModel):
    """Тело шагов 2 и 3."""

    upload_id: str = Field(description="SHA-256 принятого файла — он же его имя в хранилище.")
    data_kind: DataKind
    mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Поле Системы → колонка файла. Направление однозначное: у поля один источник.",
    )


class TemplateBody(MappingBody):
    """Тело сохранения шаблона сопоставления."""

    name: str


class RollbackBody(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.get("/kinds", summary="Типы загружаемых данных")
def list_kinds(_: ImportUser) -> dict[str, Any]:
    """Шесть плиток шага 1 вместе с каноническими полями каждой.

    Ограничения возвращаются сервером, а не зашиваются в интерфейс: предел
    размера файла задан настройкой, и вторая его копия в коде клиента рано или
    поздно разойдётся с настоящей.
    """
    settings = get_settings()
    return {
        "kinds": import_wizard.describe_kinds(),
        "accepted_extensions": sorted(import_wizard.ACCEPTED_EXTENSIONS),
        "max_upload_mb": settings.max_upload_mb,
        "background_row_threshold": import_wizard.BACKGROUND_ROW_THRESHOLD,
    }


@router.post("/upload", summary="Шаг 1: принять файл")
async def upload(
    session: DbSession,
    user: ImportUser,
    data_kind: Annotated[DataKind, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    """Принять файл, зафиксировать его по хешу и разобрать структуру.

    Содержимое читается целиком в память: предел в 50 МБ задан ТЗ, и потоковая
    обработка ради него усложнила бы разбор XLSX, который всё равно требует
    произвольного доступа к файлу.
    """
    content = await file.read()
    try:
        result = import_wizard.accept_upload(
            session,
            file_name=file.filename or "без-имени",
            content=content,
            kind=data_kind,
            user=user,
        )
    except ImportWizardError as error:
        raise _fail(error) from error

    session.commit()
    payload = result.as_dict()
    payload["templates"] = import_wizard.list_mapping_templates(session, data_kind)
    return payload


@router.get("/templates", summary="Сохранённые шаблоны сопоставления")
def templates(
    session: DbSession,
    _: ImportUser,
    data_kind: Annotated[DataKind | None, Query()] = None,
) -> list[dict[str, Any]]:
    return import_wizard.list_mapping_templates(session, data_kind)


@router.post("/templates", summary="Сохранить шаблон сопоставления", status_code=201)
def save_template(session: DbSession, _: ImportUser, body: TemplateBody) -> dict[str, Any]:
    """Запомнить сопоставление, чтобы не повторять его для той же выгрузки."""
    try:
        source_file = import_wizard.source_file_for(session, body.upload_id)
        dataset = import_wizard.save_mapping_template(
            session,
            name=body.name,
            kind=body.data_kind,
            mapping=body.mapping,
            source_file_id=source_file.id,
        )
    except ImportWizardError as error:
        raise _fail(error) from error

    session.commit()
    return {
        "id": str(dataset.id),
        "name": body.name,
        "data_kind": str(body.data_kind),
        "mapping": body.mapping,
        "file_name": source_file.file_name,
    }


@router.post("/dry-run", summary="Шаг 3: сухой прогон")
def dry_run(
    session: DbSession,
    user: ImportUser,
    context: RequestCtx,
    body: MappingBody,
) -> dict[str, Any]:
    """Проверить файл и показать, что произойдёт, ничего не записав.

    Возвращаются и сводка, и построчные замечания: ТЗ требует указывать строку
    и колонку, а сводка без адресов не даёт исправить файл.
    """
    try:
        job = import_wizard.dry_run(
            session,
            upload_id=body.upload_id,
            kind=body.data_kind,
            mapping=body.mapping,
            user=user,
            context=context,
        )
    except ImportWizardError as error:
        raise _fail(error) from error

    payload = import_wizard.job_payload(session, job, with_issues=True)
    session.commit()
    return payload


@router.post("/confirm", summary="Шаг 3: подтвердить загрузку")
def confirm(
    session: DbSession,
    user: ImportUser,
    context: RequestCtx,
    body: MappingBody,
    background_tasks: BackgroundTasks,
    background: Annotated[bool, Query(description="Обработать в фоне с прогрессом.")] = False,
) -> dict[str, Any]:
    """Записать данные новой логической версией.

    Фоновый режим включается явным параметром, а не решением сервера: оператор
    должен понимать, дождётся он результата или будет следить за прогрессом.
    Мастер подсказывает режим по числу строк, но выбор остаётся за человеком.
    """
    if background:
        background_tasks.add_task(
            import_wizard.confirm_in_background,
            upload_id=body.upload_id,
            kind=body.data_kind,
            mapping=body.mapping,
            user_id=user.id,
        )
        return {
            "accepted": True,
            "background": True,
            "message": (
                "Файл принят в обработку. Прогресс виден в истории загрузок; "
                "по завершении задание получит статус «успешно»."
            ),
        }

    try:
        result = import_wizard.confirm(
            session,
            upload_id=body.upload_id,
            kind=body.data_kind,
            mapping=body.mapping,
            user=user,
            context=context,
        )
    except ImportWizardError as error:
        raise _fail(error) from error

    payload = import_wizard.job_payload(session, result.job, with_issues=True)
    payload["background"] = False
    session.commit()
    return payload


@router.get("/jobs", summary="История загрузок")
def jobs(
    session: DbSession,
    _: ImportUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    layer_code: Annotated[str | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Правая колонка мастера: последние загрузки со статусными бейджами."""
    return import_wizard.job_history(session, limit=limit, layer_code=layer_code)


@router.get("/jobs/{job_id}", summary="Карточка загрузки")
def job(session: DbSession, _: ImportUser, job_id: uuid.UUID) -> dict[str, Any]:
    """Одно задание целиком: счётчики, прогресс и построчные замечания."""
    found = session.get(ImportJob, job_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Задание импорта не найдено"
        )
    return import_wizard.job_payload(session, found, with_issues=True)


@router.post("/jobs/{job_id}/rollback", summary="Откатить логическую версию")
def rollback(
    session: DbSession,
    user: RollbackUser,
    context: RequestCtx,
    job_id: uuid.UUID,
    body: RollbackBody,
) -> dict[str, Any]:
    """Снять актуальность с версии. Данные при этом не удаляются."""
    try:
        job_row = import_wizard.rollback(
            session, job_id=job_id, user=user, context=context, reason=body.reason
        )
    except ImportWizardError as error:
        raise _fail(error) from error

    payload = import_wizard.job_payload(session, job_row)
    session.commit()
    return payload


__all__ = ["router"]
