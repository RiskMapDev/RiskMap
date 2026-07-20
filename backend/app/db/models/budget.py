"""Слой 8.3 «Бюджетные риски»: бюджетная классификация, факты, расчёт по месяцам.

Три таблицы отражают три уровня, на которых существуют данные этого слоя.

`BudgetProgram` — справочник статей бюджетной классификации. Иерархия глубиной
пять уровней (0–4) восстанавливается по `parent_id`; корневых разделов
одиннадцать, от «I. ДОХОДЫ» до справочных остатков.

`BudgetFact` — факт по одной статье для одной области за один месяц. 74 831
строка. Все накопительные величины (`plgp`, `sumrg`, `obz`) хранятся ровно
так, как в источнике, то есть **нарастающим итогом с начала года**. Приводить
их к месячным приращениям при импорте нельзя: разность двух YTD-значений —
это уже расчёт, и он должен быть виден как расчёт, а не выдавать себя за
исходные данные.

`BudgetMonthlyMetric` — расчётная строка «область × месяц», 240 записей.

Про `territory_id`. В книге он свой (`REG-001`…`REG-020`) и к справочнику
территорий проекта отношения не имеет: КАТО в книге 8.3 отсутствует
полностью, ни в сырых данных, ни в расчёте. Поэтому здесь хранятся оба ключа —
код книги в `source_territory_code` и ссылка на справочник в `territory_id`,
проставляемая резолвером по названию области. Ссылка необязательна: если
название не опознано, строка обязана загрузиться и попасть в отчёт о качестве,
а не потерять данные.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, uuid_pk

# Денежные величины книги достигают десятков миллиардов и имеют три знака
# после запятой. Numeric, а не float: суммы сверяются с контрольными
# значениями книги до копейки, и накопленная ошибка double здесь недопустима.
_MONEY = Numeric(20, 3)

# Доли и коэффициенты индикаторов: R07/R08 измеряются в месяцах и доходят до
# десятков, R13 — индекс в [0, 1]. Общий тип с запасом по целой части.
_RATIO = Numeric(18, 9)


class BudgetProgram(Base, TimestampMixin, ProvenanceMixin):
    """Статья бюджетной классификации.

    `code` в источнике не уникален и местами пуст (3 225 строк из 74 831), а
    `name` — наоборот, заполнен всегда и служит основным классификационным
    признаком. Поэтому первичным ключом остаётся UUID, а естественная
    уникальность объявлена по паре «код + наименование»: одно и то же название
    встречается на разных уровнях иерархии с разными кодами.
    """

    __tablename__ = "budget_programs"
    __table_args__ = (
        UniqueConstraint("code", "name", "level", name="uq_budget_program_code_name_level"),
        Index("ix_budget_programs_parent", "parent_id"),
        Index("ix_budget_programs_level", "level"),
        CheckConstraint("level BETWEEN 0 AND 4", name="ck_budget_program_level_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    code: Mapped[str | None] = mapped_column(
        String(32),
        doc="Код статьи. Пуст у 4,3 % строк источника — это агрегаты без кода.",
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    level: Mapped[int] = mapped_column(
        nullable=False, doc="Уровень иерархии 0–4; 0 — один из одиннадцати корневых разделов."
    )
    is_leaf: Mapped[bool] = mapped_column(nullable=False, default=False)

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budget_programs.id", ondelete="RESTRICT")
    )
    parent: Mapped[BudgetProgram | None] = relationship(
        remote_side="BudgetProgram.id", back_populates="children"
    )
    children: Mapped[list[BudgetProgram]] = relationship(
        back_populates="parent", cascade="save-update"
    )

    source_parent_code: Mapped[int | None] = mapped_column(
        doc="Код родителя из источника — для восстановления иерархии при импорте."
    )

    facts: Mapped[list[BudgetFact]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<BudgetProgram {self.code} {self.name[:40]!r} level={self.level}>"


class BudgetFact(Base, TimestampMixin, ProvenanceMixin):
    """Исполнение одной статьи бюджета в одной области за один месяц.

    Единица — строка листа `RAW_DATA`. Ключ `(program, territory, period)`
    уникален: дубликатов по тройке «регион + период + идентификатор строки» в
    источнике нет (проверено при аудите).

    `period_month`/`period_year` разложены из строки `MM.YYYY`. Хранить период
    строкой, как в источнике, было бы удобнее для сверки, но невозможно
    сортировать и фильтровать по диапазону, а сортировать придётся: месячные
    приращения считаются как разность соседних YTD-значений.
    """

    __tablename__ = "budget_facts"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "source_territory_code",
            "period_year",
            "period_month",
            name="uq_budget_fact_program_territory_period",
        ),
        Index("ix_budget_facts_territory_period", "territory_id", "period_year", "period_month"),
        Index("ix_budget_facts_period", "period_year", "period_month"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_budget_fact_month_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budget_programs.id", ondelete="CASCADE"), nullable=False
    )
    program: Mapped[BudgetProgram] = relationship(back_populates="facts")

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("territories.id", ondelete="RESTRICT"),
        doc=(
            "Ссылка на справочник территорий. Необязательна: КАТО в книге 8.3 "
            "нет, привязка идёт по названию области, и неопознанное название "
            "не должно ронять импорт."
        ),
    )
    source_territory_code: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="Код территории из книги: REG-001…REG-020.",
    )
    source_region_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc=(
            "Название области ровно как в источнике, включая опечатки "
            "«Западно-Казахстанкая» и «Северо-Казахстанкая». Исправленная "
            "форма живёт в справочнике алиасов, здесь — свидетельство."
        ),
    )

    period: Mapped[str] = mapped_column(
        String(7), nullable=False, doc="Период как в источнике: строка «MM.YYYY»."
    )
    period_month: Mapped[int] = mapped_column(nullable=False)
    period_year: Mapped[int] = mapped_column(nullable=False)

    utv: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, doc="Утверждённый годовой бюджет.")
    utch: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, doc="Уточнённый бюджет.")
    plg: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, doc="Годовой план.")
    plgp: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, doc="План на отчётный период, нарастающим итогом."
    )
    plgo: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, doc="План по обязательствам.")
    sumrg: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, doc="Кассовое исполнение, нарастающим итогом."
    )
    obz: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, doc="Принятые обязательства, нарастающим итогом."
    )
    obzsumrg: Mapped[Decimal] = mapped_column(
        _MONEY, nullable=False, doc="Неоплаченные обязательства: обязательства минус касса."
    )

    plgpsumrg: Mapped[Decimal | None] = mapped_column(
        _RATIO, doc="Исполнение плана периода, % — приведено источником."
    )
    plgsumrg: Mapped[Decimal | None] = mapped_column(
        _RATIO, doc="Исполнение годового плана, % — приведено источником."
    )

    source_row_id: Mapped[int | None] = mapped_column(
        doc=(
            "Идентификатор строки внутри среза. Устойчивым территориальным ID "
            "не является — уникален только в паре «регион + период»."
        )
    )

    def __repr__(self) -> str:
        return f"<BudgetFact {self.source_territory_code} {self.period} program={self.program_id}>"


class BudgetMonthlyMetric(Base, TimestampMixin, ProvenanceMixin):
    """Расчётная строка «область × месяц»: 15 индикаторов и итоговый балл.

    240 записей — 20 областей на 12 месяцев 2025 года. Сохраняются и сырые
    показатели индикаторов, и итог, потому что показать пользователю «почему
    такой балл» без сырых величин невозможно, а пересчитывать их на лету
    означало бы заново поднимать 74 831 строку фактов.

    Две «полноты» в этой таблице разные и обе нужны:

    * `data_completeness` — величина книги `1 − флаги/3`, качество исходной
      агрегации. У 32 строк она равна 0,667: в этих срезах отсутствует раздел
      «IV. Сальдо по операциям с финансовыми активами».
    * `indicator_completeness` — доля измеренного веса модели. В этом слое она
      всегда 1: все 15 индикаторов посчитаны на каждой строке.

    Ни та, ни другая не превращает уровень в серый — «серого» уровня в
    методике 8.3 нет, в отличие от слоя 8.4.
    """

    __tablename__ = "budget_monthly_metrics"
    __table_args__ = (
        UniqueConstraint(
            "source_territory_code",
            "period_year",
            "period_month",
            "model_version",
            name="uq_budget_metric_territory_period_version",
        ),
        Index("ix_budget_metrics_territory", "territory_id"),
        Index("ix_budget_metrics_period", "period_year", "period_month"),
        Index("ix_budget_metrics_level", "risk_level"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_budget_metric_month_range"),
        CheckConstraint(
            "risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)",
            name="ck_budget_metric_score_range",
        ),
        CheckConstraint(
            "data_completeness >= 0 AND data_completeness <= 1",
            name="ck_budget_metric_completeness_range",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()

    territory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("territories.id", ondelete="RESTRICT")
    )
    source_territory_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_region_name: Mapped[str] = mapped_column(String(255), nullable=False)
    territory_name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)

    geo_level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="REGION",
        doc="В книге 8.3 всегда REGION: районов в слое нет, это общереспубликанский разрез.",
    )
    parent_territory_code: Mapped[str | None] = mapped_column(String(16))

    period: Mapped[str] = mapped_column(String(7), nullable=False)
    period_month: Mapped[int] = mapped_column(nullable=False)
    period_year: Mapped[int] = mapped_column(nullable=False)

    # --- сырые показатели индикаторов ---------------------------------------

    r01_revenue_execution: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r02_expense_execution: Mapped[Decimal] = mapped_column(
        _RATIO,
        nullable=False,
        doc="Тот же показатель питает R03 — методика нормирует его в обе стороны.",
    )
    r04_revision_intensity: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r05_profile_error: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r06_balance_deviation: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r07_cash_buffer_months: Mapped[Decimal] = mapped_column(
        _RATIO,
        nullable=False,
        doc="Тот же показатель питает R08 — двойной счёт ликвидности на 9 % веса.",
    )
    r09_absorption_pressure: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r10_commitment_lag: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r11_unpaid_commitments: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r12_underexecution_width: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r13_expense_hhi: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r14_financial_ops_deviation: Mapped[Decimal] = mapped_column(_RATIO, nullable=False)
    r15_quality_flags: Mapped[int] = mapped_column(
        nullable=False, default=0, doc="Число флагов качества данных на строке, 0–3."
    )

    closing_balance: Mapped[Decimal] = mapped_column(
        _MONEY,
        nullable=False,
        doc=(
            "Конечный остаток бюджетных средств. Индикатором не является, но "
            "входит в условие критического переопределения."
        ),
    )

    # --- результат расчёта ---------------------------------------------------

    model_code: Mapped[str] = mapped_column(String(16), nullable=False, default="8.3")
    model_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        doc="Версия модели на момент расчёта: правка весов не переписывает историю оценок.",
    )

    risk_score: Mapped[Decimal | None] = mapped_column(_RATIO)
    risk_level: Mapped[str | None] = mapped_column(String(16))
    rank_in_month: Mapped[int | None] = mapped_column(
        doc="Ранг внутри месяца, 1 — самый рискованный. Тай-брейк по коду территории."
    )

    data_completeness: Mapped[Decimal] = mapped_column(
        Numeric(6, 5),
        nullable=False,
        doc="Полнота по книге: 1 − флаги/3. На уровень риска в слое 8.3 не влияет.",
    )
    indicator_completeness: Mapped[Decimal] = mapped_column(
        Numeric(6, 5),
        nullable=False,
        doc="Доля измеренного веса модели. В этом слое всегда 1.",
    )

    override_triggered: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc=(
            "Сработал ли пол в 75 баллов. Именно пол, а не замена уровня: "
            "балл такой строки равен ровно 75,0."
        ),
    )
    missing_roots_flag: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc="В срезе отсутствует один из ключевых корневых разделов — 32 строки книги.",
    )

    factors: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, doc="Расшифровка вклада каждого индикатора — для карточки объекта."
    )
    explanation_ru: Mapped[str | None] = mapped_column(
        Text, doc="Перечень индикаторов с баллом не ниже 50 — текст для пользователя."
    )

    def __repr__(self) -> str:
        return (
            f"<BudgetMonthlyMetric {self.source_territory_code}-{self.period_month:02d} "
            f"score={self.risk_score} level={self.risk_level}>"
        )


__all__ = ["BudgetFact", "BudgetMonthlyMetric", "BudgetProgram"]
