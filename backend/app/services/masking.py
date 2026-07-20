"""Маскирование персональных данных — ИИН и БИН.

ИИН есть в данных субсидий и в графе связей, и это персональные данные. Роль
определяет, что увидит пользователь:

    FULL    полное значение, и каждый такой просмотр попадает в журнал
    MASKED  8407******12 — видно, что значение есть, и можно сверить две строки
    HIDDEN  значения нет вовсе, отдаётся только признак наличия

Устройство модуля подчинено одной мысли: **полное значение нельзя получить
мимо журнала**. Поэтому функция раскрытия сама пишет запись `SENSITIVE_VIEW` и
требует для этого пользователя и контекст запроса. Вариант «вернуть значение, а
журналировать в вызывающем коде» отвергнут: он работает ровно до первого нового
эндпоинта, автор которого про журнал забудет, и провал такой проверки заметен
только на аудите, то есть слишком поздно.

Почему маска именно 4 + 2. Первые четыре цифры ИИН — дата рождения (ГГММ), они
и так выводятся из других полей карточки и потому не добавляют раскрытия.
Последние две дают возможность различить две записи глазами, не восстанавливая
номер: серединные шесть цифр, включая контрольный разряд, остаются закрыты.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.orm import Session

from app.core.permissions import sensitive_access_of
from app.db.models.access import SensitiveDataAccess, User
from app.services import audit
from app.services.audit import RequestContext

MASK_CHAR: Final = "*"

#: Сколько знаков видно с начала и с конца в режиме MASKED.
VISIBLE_PREFIX: Final = 4
VISIBLE_SUFFIX: Final = 2

#: Короче этого значение маскируется целиком: у восьмизначного номера открытые
#: шесть знаков из восьми — это уже не маска, а публикация.
_MIN_LENGTH_FOR_PARTIAL: Final = VISIBLE_PREFIX + VISIBLE_SUFFIX + 1


@dataclass(frozen=True, slots=True)
class MaskedValue:
    """Персональное значение в том виде, в каком его можно отдать наружу."""

    access: SensitiveDataAccess
    value: str | None
    present: bool

    @property
    def is_masked(self) -> bool:
        return self.access is SensitiveDataAccess.MASKED and self.present

    @property
    def is_hidden(self) -> bool:
        return self.access is SensitiveDataAccess.HIDDEN

    def to_dict(self) -> dict[str, Any]:
        """Представление для ответа API.

        `present` отдаётся всегда, в том числе при HIDDEN: интерфейсу нужно
        отличать «ИИН не заполнен» от «вам не положено его видеть», иначе
        пользователь будет считать данные неполными и заводить обращения о
        пропаже сведений.
        """
        return {"value": self.value, "present": self.present, "access": str(self.access)}


def mask_identifier(raw: str | None) -> str | None:
    """Замаскировать ИИН/БИН по правилу «первые 4 и последние 2».

    Пробелы по краям снимаются, но сама строка не нормализуется и не
    валидируется: задача маски — скрыть, а не чинить данные. Значение, пришедшее
    из источника с дефисами или лишними знаками, будет замаскировано как есть,
    и это правильнее, чем молча подменить его «исправленным».
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) < _MIN_LENGTH_FOR_PARTIAL:
        return MASK_CHAR * len(value)
    hidden = len(value) - VISIBLE_PREFIX - VISIBLE_SUFFIX
    return f"{value[:VISIBLE_PREFIX]}{MASK_CHAR * hidden}{value[-VISIBLE_SUFFIX:]}"


def _has_value(raw: str | None) -> bool:
    return bool(raw and raw.strip())


def render_for_access(raw: str | None, access: SensitiveDataAccess) -> MaskedValue:
    """Применить степень доступа к значению — без журналирования.

    Отдельно от `reveal` намеренно: этой функцией пользуются тесты и режимы
    MASKED/HIDDEN, где раскрытия не происходит и писать в журнал нечего. Для
    FULL напрямую её вызывать нельзя — для этого есть `reveal`.
    """
    present = _has_value(raw)
    if not present:
        # Отсутствующее значение одинаково выглядит для всех ролей: скрывать
        # нечего, и разное поведение здесь только путало бы.
        return MaskedValue(access=access, value=None, present=False)

    if access is SensitiveDataAccess.FULL:
        return MaskedValue(access=access, value=raw.strip() if raw else None, present=True)
    if access is SensitiveDataAccess.MASKED:
        return MaskedValue(access=access, value=mask_identifier(raw), present=True)
    return MaskedValue(access=SensitiveDataAccess.HIDDEN, value=None, present=True)


def reveal(
    raw: str | None,
    *,
    user: User,
    session: Session | None = None,
    context: RequestContext | None = None,
    field: str = "iin",
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
) -> MaskedValue:
    """Отдать значение согласно роли пользователя, журналируя раскрытие.

    Единственная точка, через которую полный ИИН попадает наружу. Журнал
    пишется до возврата значения: если запись не удалась, не должно вернуться и
    значение.
    """
    access = sensitive_access_of(user)
    result = render_for_access(raw, access)

    # Журналируется только фактическое раскрытие: запись «посмотрел маску» не
    # несёт смысла и за месяц утопит настоящие события в шуме.
    if result.access is SensitiveDataAccess.FULL and result.present:
        audit.record_sensitive_view(
            session,
            user,
            field=field,
            entity_type=entity_type,
            entity_id=entity_id,
            context=context,
        )
    return result


def reveal_many(
    values: Sequence[str | None],
    *,
    user: User,
    session: Session | None = None,
    context: RequestContext | None = None,
    field: str = "iin",
    entity_type: str | None = None,
) -> list[MaskedValue]:
    """То же для списка — одна запись журнала на выборку.

    Запись на каждую строку сделала бы журнал нечитаемым: выгрузка таблицы
    субсидий породила бы двадцать тысяч событий об одном действии. Поэтому
    пишется одно событие с числом раскрытых значений — этого достаточно, чтобы
    увидеть и сам факт, и его масштаб.
    """
    access = sensitive_access_of(user)
    results = [render_for_access(raw, access) for raw in values]

    revealed = sum(
        1 for item in results if item.access is SensitiveDataAccess.FULL and item.present
    )
    if revealed:
        audit.record_sensitive_view(
            session,
            user,
            field=field,
            entity_type=entity_type,
            count=revealed,
            context=context,
        )
    return results


__all__ = [
    "MASK_CHAR",
    "VISIBLE_PREFIX",
    "VISIBLE_SUFFIX",
    "MaskedValue",
    "mask_identifier",
    "render_for_access",
    "reveal",
    "reveal_many",
]
