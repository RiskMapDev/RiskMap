"""Сопоставление названий территорий из книг с записями справочника.

Задача возникла не от хорошей жизни. Кода КАТО в источниках нет ни у одного
района, поэтому единственный способ связать строку книги с территорией —
название. А названия в книгах написаны как придётся:

    «Талгарский район» · «Талгарский р-н» · «Талгарский»
    «Қонаев Г.А.» · «Конаев» · «г. Конаев»
    «Сарканский» · «Саркандский»
    «Енбекшиказахский» · «Енбекшіқазақский»

Свёртка приводит написание к канонической форме, снимая различия, которые
заведомо не несут смысла: тип единицы, регистр, пунктуацию, казахскую и русскую
графику. Всё остальное — опечатки, устаревшие и просто другие названия —
свёрткой не лечится и разрешается через таблицу алиасов, где у каждого
написания есть источник.

Принцип, которого держится этот модуль: **непонятое название не угадывается**.
Если совпадение неоднозначно или его нет, возвращается явный отказ с причиной,
и строка отправляется в отчёт о качестве данных. Молча привязать субсидию не к
тому району — намного хуже, чем показать пользователю «территория не определена».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

# Казахские буквы приводятся к близким русским: книги пишут одни и те же
# названия то так, то так, и различие графики смысла не несёт.
_CYRILLIC_FOLDING = str.maketrans(
    {
        "ә": "а",
        "ғ": "г",
        "қ": "к",
        "ң": "н",
        "ө": "о",
        "ұ": "у",
        "ү": "у",
        "һ": "х",
        "і": "и",
        "ё": "е",
    }
)

# Обозначения типа единицы. Снимаются регулярными выражениями ДО удаления
# пунктуации: сокращения «р-н», «г.а.», «с.о.» держатся именно на дефисе и
# точках, и если сначала вычистить пунктуацию, они распадутся на бессмысленные
# однобуквенные слова и перестанут распознаваться.
#
# Порядок значим: более длинные и составные формы идут раньше, иначе «с.о.»
# будет съедено правилом для «с.».
_TYPE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bгородская\s+администрация\b",
        r"\b(?:аульный|сельский)\s+округ\b",
        r"\bг\s*\.?\s*а\s*\.(?=\s|$)",  # «Қонаев Г.А.»
        r"\bс\s*\.\s*о\s*\.?(?=\s|$)",
        r"\bр\s*-\s*н\b",
        r"\bрайон\w*\b",
        r"\bаудан\w*\b",
        r"\bкалас\w*\b",
        r"\bобласт\w*\b",
        r"\bобл\s*\.(?=\s|$)",
        r"\bгород\b",
        r"\bгор\s*\.(?=\s|$)",
        r"\bг\s*\.(?=\s*\S)",  # префикс «г. Конаев»
        r"\bсело\b",
        r"\bс\s*\.(?=\s*\S)",
        r"\bпоселок\b",
        r"\bпос\s*\.(?=\s*\S)",
    )
)

_PUNCTUATION = re.compile(r"[«»\"'`.,;:()\[\]/\\—–\-]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_territory_name(raw: str) -> str:
    """Свернуть название территории к канонической форме для сравнения.

    Свёртка намеренно агрессивна к типу единицы и графике, но не трогает
    основу названия: «Сарканский» и «Саркандский» останутся разными строками
    и должны разрешаться через алиас, а не подгонкой правил свёртки. Иначе
    правила начнут склеивать действительно разные территории.
    """
    text = unicodedata.normalize("NFC", raw).strip().casefold()
    text = text.translate(_CYRILLIC_FOLDING)

    # Тип единицы снимается по границам слов, поэтому «город» не выкусывается
    # из «Городовиковский».
    stripped = text
    for pattern in _TYPE_PATTERNS:
        stripped = pattern.sub(" ", stripped)

    stripped = _PUNCTUATION.sub(" ", stripped)
    stripped = _WHITESPACE.sub(" ", stripped).strip()

    if stripped:
        return stripped

    # От названия остались одни обозначения типа («район» без имени). Возвращаем
    # исходную свёртку: пустая строка склеила бы все такие значения в одно.
    fallback = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", fallback).strip()


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    """Название подходит нескольким территориям — угадывать нельзя."""

    NOT_FOUND = "not_found"
    EMPTY = "empty"
    """В источнике пусто. Это не ошибка сопоставления, а отсутствие данных."""


@dataclass(frozen=True, slots=True)
class Resolution:
    """Результат сопоставления одного названия."""

    status: ResolutionStatus
    raw: str
    normalized: str
    territory_code: str | None = None
    candidates: tuple[str, ...] = ()
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status is ResolutionStatus.RESOLVED

    def require(self) -> str:
        """Код территории или исключение.

        Нужен там, где продолжать без территории бессмысленно. В импортёрах
        предпочтителен разбор `status`: строка без территории должна попасть
        в отчёт о качестве, а не уронить весь импорт.
        """
        if self.territory_code is None:
            raise ValueError(f"Территория не определена для {self.raw!r}: {self.reason}")
        return self.territory_code


class TerritoryResolver:
    """Сопоставитель названий.

    Строится из справочника алиасов один раз и дальше работает по памяти:
    импорт 21 521 строки субсидий не должен ходить в базу за каждой строкой.
    """

    def __init__(self, aliases: Mapping[str, str] | None = None) -> None:
        self._index: dict[str, set[str]] = {}
        if aliases:
            for alias, code in aliases.items():
                self.add(alias, code)

    def add(self, alias: str, territory_code: str) -> None:
        """Добавить написание.

        Одно написание может указывать на несколько территорий — это не
        ошибка загрузки справочника, а факт, который вскроется при
        сопоставлении как неоднозначность.
        """
        normalized = normalize_territory_name(alias)
        if not normalized:
            return
        self._index.setdefault(normalized, set()).add(territory_code)

    def add_many(self, pairs: Iterable[tuple[str, str]]) -> None:
        for alias, code in pairs:
            self.add(alias, code)

    @property
    def known_names(self) -> int:
        return len(self._index)

    @property
    def ambiguous_names(self) -> tuple[str, ...]:
        """Написания, указывающие больше чем на одну территорию."""
        return tuple(sorted(name for name, codes in self._index.items() if len(codes) > 1))

    def resolve(self, raw: str | None) -> Resolution:
        """Сопоставить название территории."""
        if raw is None or not str(raw).strip():
            return Resolution(
                status=ResolutionStatus.EMPTY,
                raw="" if raw is None else str(raw),
                normalized="",
                reason="в источнике не указана территория",
            )

        raw_text = str(raw)
        normalized = normalize_territory_name(raw_text)

        codes = self._index.get(normalized)
        if not codes:
            return Resolution(
                status=ResolutionStatus.NOT_FOUND,
                raw=raw_text,
                normalized=normalized,
                reason="написание отсутствует в справочнике алиасов",
            )

        if len(codes) > 1:
            return Resolution(
                status=ResolutionStatus.AMBIGUOUS,
                raw=raw_text,
                normalized=normalized,
                candidates=tuple(sorted(codes)),
                reason=f"написание подходит {len(codes)} территориям",
            )

        return Resolution(
            status=ResolutionStatus.RESOLVED,
            raw=raw_text,
            normalized=normalized,
            territory_code=next(iter(codes)),
        )


@dataclass(frozen=True, slots=True)
class ResolutionReport:
    """Сводка сопоставления по одному импорту.

    Нужна затем, чтобы неразобранные названия были видны как число, а не
    растворялись среди успешных строк.
    """

    total: int
    resolved: int
    ambiguous: tuple[Resolution, ...]
    not_found: tuple[Resolution, ...]
    empty: int

    @property
    def unresolved(self) -> int:
        return len(self.ambiguous) + len(self.not_found) + self.empty

    @property
    def resolved_share(self) -> float:
        return self.resolved / self.total if self.total else 0.0

    def summary_ru(self) -> str:
        parts = [f"сопоставлено {self.resolved} из {self.total}"]
        if self.not_found:
            parts.append(f"не найдено {len(self.not_found)}")
        if self.ambiguous:
            parts.append(f"неоднозначно {len(self.ambiguous)}")
        if self.empty:
            parts.append(f"без территории {self.empty}")
        return ", ".join(parts)


def build_report(resolutions: Iterable[Resolution]) -> ResolutionReport:
    items = list(resolutions)
    return ResolutionReport(
        total=len(items),
        resolved=sum(1 for r in items if r.status is ResolutionStatus.RESOLVED),
        ambiguous=tuple(r for r in items if r.status is ResolutionStatus.AMBIGUOUS),
        not_found=tuple(r for r in items if r.status is ResolutionStatus.NOT_FOUND),
        empty=sum(1 for r in items if r.status is ResolutionStatus.EMPTY),
    )
