"""Эндпоинты отчётности и экспорта.

Один рабочий метод: `POST /reports/{template}` с телом `QuerySpec` и
параметром формата. Метод POST, а не GET, потому что выборка — вложенная
структура с десятком списков, и загонять её в строку запроса пришлось бы
сериализацией, которую потом никто не смог бы прочитать глазами.

Права требуются оба сразу — «формирование отчётов» и «выгрузка данных».
Отчёт всегда возвращается файлом, то есть выносит данные за периметр системы,
а именно за это отвечает `export.data` (см. `app/core/permissions.py`). Роли,
которым отчёты положены по ТЗ, — аналитик и руководитель — обладают обоими
правами; роль «Просмотр» не обладает ни одним, и это верно: возможность
скачать выборку в файл — не то же самое, что возможность посмотреть её на
экране.

События пишутся два: `REPORT_GENERATED` — внутри сборки данных (иначе новый
эндпоинт мог бы обойти журнал), `EXPORT` — здесь, после успешной отрисовки.
Порядок важен: журналировать выгрузку до того, как файл собран, значило бы
записывать в журнал события, которых не было.
"""

from __future__ import annotations

import io
import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession, RequestCtx
from app.api.queryspec import QuerySpec
from app.core.permissions import (
    CurrentTerritoryScope,
    PermissionCode,
    TerritoryScope,
    require_permission,
)
from app.db.models.access import User
from app.db.models.territory import Territory
from app.services import report_render, reports
from app.services.report_render import PdfUnavailableError, ReportFormat
from app.services.reports import ReportTemplate

router = APIRouter(prefix="/reports", tags=["отчёты"])

#: Право на формирование и право на выгрузку одновременно — см. docstring модуля.
_REQUIRE_REPORT = Depends(
    require_permission(PermissionCode.REPORT_GENERATE, PermissionCode.EXPORT_DATA)
)


@router.get("/templates", summary="Каталог шаблонов отчётов")
def list_templates() -> list[dict[str, str]]:
    """Восемь шаблонов ТЗ — для сетки карточек на экране «Отчёты и экспорт».

    Права здесь не проверяются: перечень шаблонов не содержит данных и нужен
    интерфейсу, чтобы показать карточки в неактивном виде тому, кому отчёты не
    положены. Прятать сам факт существования раздела бессмысленно — он описан
    в ТЗ, доступном шире, чем система.
    """
    return reports.template_catalog()


@router.get("/formats", summary="Доступные форматы выгрузки")
def list_formats() -> list[dict[str, Any]]:
    """Форматы и их доступность в этом развёртывании.

    PDF показывается всегда, но с признаком доступности: интерфейс обязан
    заранее знать, что кнопка не сработает, а не выяснять это после нажатия.
    """
    pdf_ready = report_render.pdf_available()
    return [
        {
            "code": str(ReportFormat.DOCX),
            "title": "Microsoft Word",
            "media_type": ReportFormat.DOCX.media_type,
            "available": True,
            "reason": "",
        },
        {
            "code": str(ReportFormat.XLSX),
            "title": "Microsoft Excel",
            "media_type": ReportFormat.XLSX.media_type,
            "available": True,
            "reason": "",
        },
        {
            "code": str(ReportFormat.PDF),
            "title": "PDF",
            "media_type": ReportFormat.PDF.media_type,
            "available": pdf_ready,
            "reason": (
                ""
                if pdf_ready
                else "Не установлен reportlab или отсутствует файл кириллического шрифта."
            ),
        },
    ]


@router.post(
    "/{template}",
    summary="Сформировать отчёт и выгрузить файлом",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "Файл отчёта"},
        501: {"description": "Формат не поддерживается в этом развёртывании"},
    },
)
def generate_report(
    template: ReportTemplate,
    session: DbSession,
    context: RequestCtx,
    scope: CurrentTerritoryScope,
    user: Annotated[User, _REQUIRE_REPORT],
    spec: Annotated[QuerySpec | None, Body(description="Выборка отчёта")] = None,
    report_format: Annotated[
        ReportFormat, Query(alias="format", description="Формат выгрузки")
    ] = ReportFormat.DOCX,
) -> StreamingResponse:
    """Собрать отчёт по выборке и отдать файл потоком."""
    query = spec or QuerySpec()

    allowed = _allowed_ids(scope)
    document = reports.build_report(
        session,
        template,
        query,
        user=user,
        context=context,
        allowed_territory_ids=allowed,
        scope_territory_name=_scope_name(session, scope),
    )

    try:
        payload = report_render.render(document, report_format)
    except PdfUnavailableError as exc:
        # 501, а не 500: сервер исправен, но такой возможности в этом
        # развёртывании нет. Текст исключения объясняет, чего именно не хватает,
        # и его надо отдать целиком — иначе администратор будет угадывать.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"Выгрузка в {report_format.value.upper()} недоступна. {exc} "
                "Отчёт можно выгрузить в Word или Excel — данные в них те же."
            ),
        ) from exc

    file_name = document.file_stem + report_format.extension

    reports.record_export(
        session,
        user,
        template=template,
        export_format=str(report_format),
        file_name=file_name,
        size_bytes=len(payload),
        context=context,
    )

    return StreamingResponse(
        io.BytesIO(payload),
        media_type=report_format.media_type,
        headers={
            "Content-Disposition": _content_disposition(file_name),
            "Content-Length": str(len(payload)),
            # Отчёт зависит от прав и территории пользователя — промежуточный
            # кэш не должен отдать его другому.
            "Cache-Control": "no-store",
        },
    )


def _content_disposition(file_name: str) -> str:
    """Заголовок с кириллическим именем файла по RFC 5987.

    Два имени сразу и это не избыточность. Параметр `filename` обязан быть
    ASCII — иначе часть клиентов отбросит заголовок целиком и файл сохранится
    как «download». Параметр `filename*` несёт настоящее имя в UTF-8, и его
    понимают все актуальные браузеры. Клиент, знающий `filename*`, по RFC 6266
    обязан предпочесть его, поэтому запасное имя никому не мешает.
    """
    ascii_name = _ascii_fallback(file_name)
    encoded = quote(file_name, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


#: Транслитерация для запасного ASCII-имени. Не ГОСТ и не претендует: её задача
#: — дать узнаваемое имя тем клиентам, которые не понимают RFC 5987, а не
#: обеспечить обратимость.
_TRANSLIT: dict[int, str] = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E",
        "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
        "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
        "Ф": "F", "Х": "H", "Ц": "C", "Ч": "Ch", "Ш": "Sh", "Щ": "Sch",
        "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
        " ": "_", "«": "", "»": "", '"': "", "/": "-", "\\": "-",
    }
)


def _ascii_fallback(file_name: str) -> str:
    """Запасное ASCII-имя: транслитерация плюс отбрасывание остального."""
    transliterated = file_name.translate(_TRANSLIT)
    cleaned = "".join(ch for ch in transliterated if ch.isascii() and ch not in '";\\')
    return cleaned or "report"


def _allowed_ids(scope: TerritoryScope) -> list[uuid.UUID] | None:
    """Территориальное ограничение в виде, который понимает выборка.

    `None` означает «все территории», пустой список — «ни одной». Разница
    существенна: подменить пустой список на `None` значило бы открыть
    ограниченному пользователю всю республику.
    """
    if scope.allowed_ids is None:
        return None
    return sorted(scope.allowed_ids)


def _scope_name(session: DbSession, scope: TerritoryScope) -> str | None:
    """Название территории, которой ограничен пользователь.

    Попадает в перечень применённых фильтров: ограничение роли пользователь не
    задавал, но на состав отчёта оно влияет, и умолчать о нём — значит выдать
    часть картины за целое.
    """
    if scope.root_id is None:
        return None
    territory = session.get(Territory, scope.root_id)
    return territory.name_ru if territory is not None else None


__all__ = ["router"]
