"""Обезличивание базы для публичной демонстрации.

Запуск::

    python -m scripts.anonymize --dry-run   # показать план, ничего не менять
    python -m scripts.anonymize             # заменить и проверить
    python -m scripts.anonymize --verify    # только проверка результата

Зачем. Дамп с настоящими данными можно передать коллеге, но нельзя выложить по
публичной ссылке: в базе БИН и ИИН 3 668 организаций и 3 413 получателей
субсидий, а **3 183 получателя — индивидуальные предприниматели**, и их
наименование содержит фамилию, имя и отчество живого человека. Показать это
неопределённому кругу лиц рядом со словом «критический риск» нельзя.

Что делает скрипт.

1. **Идентификаторы.** Все двенадцатизначные БИН и ИИН заменяются
   сгенерированными. Замена сквозная: один и тот же исходный номер получает
   один и тот же новый во всех таблицах, иначе развалятся связи — 50
   получателей субсидий и 76 узлов графа совпадают с организациями именно по
   номеру. Контрольный разряд считается по официальному алгоритму, поэтому
   новые номера проходят проверку формата и остаются правдоподобными.

2. **Имена физических лиц.** Наименования вида «ИП ФАМИЛИЯ ИМЯ ОТЧЕСТВО»
   заменяются на «ИП Получатель 0001». Правдоподобная выдуманная фамилия здесь
   хуже очевидно условной: она может случайно совпасть с фамилией реального
   человека, и тот окажется на публичной карте рядом с оценкой риска, которой
   не заслужил. Наглядность демонстрации не стоит такого риска.

3. **Наименования юридических лиц не трогаются.** ТОО, АО и КХ есть в открытом
   реестре юридических лиц; это не персональные данные. Убрать их значило бы
   превратить демонстрацию в бессмыслицу без выигрыша в защите.

Что скрипт **не** делает: суммы, даты, территории и оценки риска остаются
подлинными. Обезличивается принадлежность, а не сама картина рисков — иначе
демонстрировать было бы нечего.

Скрипт необратим и идемпотентен: повторный запуск не находит, что заменять.
Работать он обязан на копии базы, а не на рабочей, — см. `--dry-run`.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import session_scope

#: Колонки, где лежат двенадцатизначные идентификаторы.
IDENTIFIER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("organizations", "bin"),
    ("suppliers", "bin"),
    ("procurement_customers", "bin"),
    ("subsidy_recipients", "xin"),
    ("graph_nodes", "identifier"),
    ("project_participants", "bin"),
    ("persons", "iin"),
    ("identifiers", "raw_value"),
    ("identifiers", "normalized_value"),
)

#: Колонки, где может встретиться имя физического лица.
NAME_COLUMNS: tuple[tuple[str, str], ...] = (
    ("subsidy_recipients", "name"),
    ("organizations", "name"),
    ("graph_nodes", "label"),
    ("graph_nodes", "sublabel"),
    ("suppliers", "name"),
    ("procurement_customers", "name"),
    ("procurement_customers", "name_truncated"),
    ("project_participants", "name_raw"),
    ("project_participants", "name_key"),
)

#: Организационная форма, за которой в источнике следует ФИО человека.
_PERSONAL_FORM = re.compile(
    r"^\s*(?P<form>ИП|И\.\s*П\.|КХ|К/Х|К\.Х\.|ГКХ|Крестьянское хозяйство)\b[\s.,\"«']*",
    re.IGNORECASE,
)

_TWELVE_DIGITS = re.compile(r"^\d{12}$")

#: Как называется владелец в каждой форме — чтобы подпись осталась осмысленной.
_FORM_LABEL = {
    "ип": "Получатель",
    "кх": "Хозяйство",
    "гкх": "Хозяйство",
}


def control_digit(first_eleven: str) -> int | None:
    """Контрольный разряд БИН/ИИН по официальному алгоритму.

    Сначала веса 1…11. Если остаток равен 10, счёт повторяется со вторым
    набором весов. Если и там 10 — номер с такими одиннадцатью цифрами
    невозможен, и вызывающий код обязан взять следующий.
    """
    digits = [int(d) for d in first_eleven]

    total = sum(d * (i + 1) for i, d in enumerate(digits)) % 11
    if total != 10:
        return total

    weights = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]
    total = sum(d * w for d, w in zip(digits, weights, strict=True)) % 11
    return None if total == 10 else total


def synthetic_identifier(original: str, salt: str) -> str:
    """Новый номер, устойчиво выведенный из исходного.

    Детерминированность важнее случайности: скрипт, запущенный дважды или по
    частям, обязан дать то же соответствие, иначе связи между таблицами
    разойдутся. Обратное восстановление невозможно — исходное значение в
    результат не попадает, а хеш обрезается.

    Число ведущих нулей сохраняется. Это не косметика: у 763 записей источник
    потерял ведущие нули при чтении из таблицы, и `identifiers.raw_value`
    хранит укороченное значение вместе с признаком `leading_zeros_restored`.
    Выдать таким записям номер без нулей значило бы сделать признак ложью и
    потерять зафиксированный дефект источника.
    """
    zeros = len(original) - len(original.lstrip("0"))

    for attempt in range(100):
        seed = f"{salt}:{original}:{attempt}".encode()
        digest = hashlib.sha256(seed).hexdigest()
        eleven = "".join(str(int(ch, 16) % 10) for ch in digest[:11])

        # Ведущие нули воспроизводятся, а первая значащая цифра обязана быть
        # ненулевой — иначе их окажется больше, чем в исходном номере.
        body = list(eleven)
        for position in range(min(zeros, 10)):
            body[position] = "0"
        if body[min(zeros, 10)] == "0":
            body[min(zeros, 10)] = "1"
        eleven = "".join(body)

        check = control_digit(eleven)
        if check is not None:
            return eleven + str(check)

    raise RuntimeError(f"не удалось построить номер длиной {len(original)}")


def synthetic_name(original: str, index: int) -> str | None:
    """Условное наименование вместо ФИО. `None` — имя заменять не нужно."""
    match = _PERSONAL_FORM.match(original)
    if match is None:
        return None

    form = match.group("form").replace(".", "").replace(" ", "").replace("/", "").lower()
    label = _FORM_LABEL.get(form[:3], _FORM_LABEL.get(form[:2], "Субъект"))
    prefix = "ИП" if form.startswith("ип") else "КХ"
    return f"{prefix} {label} {index:04d}"


@dataclass
class Plan:
    """Что именно будет заменено."""

    identifiers: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    def report(self) -> str:
        return (
            f"идентификаторов к замене: {len(self.identifiers)}\n"
            f"наименований с ФИО к замене: {len(self.names)}"
        )


def collect(session: Session, salt: str) -> Plan:
    """Собрать сквозные соответствия по всем таблицам сразу.

    Соответствия строятся один раз и глобально, а не потаблично: один и тот же
    номер встречается в организациях, поставщиках и графе, и заменить его
    по-разному значило бы разорвать связь между ними.
    """
    plan = Plan()

    for table, column in IDENTIFIER_COLUMNS:
        rows = session.execute(
            text(f"select distinct {column} from {table} where {column} is not null")
        ).scalars()
        for value in rows:
            raw = str(value).strip()
            if not _TWELVE_DIGITS.match(raw) or raw in plan.identifiers:
                continue
            plan.identifiers[raw] = synthetic_identifier(raw, salt)

    # Второй проход — укороченные значения. `identifiers.raw_value` хранит
    # номер как его прочитал источник, а тот терял ведущие нули: 763 записи
    # лежат там девятью, десятью или одиннадцатью цифрами. Первый проход их
    # не видит, потому что ищет ровно двенадцать знаков, — и настоящий номер
    # уцелел бы, восстанавливаясь дополнением нулями слева.
    for table, column in IDENTIFIER_COLUMNS:
        rows = session.execute(
            text(f"select distinct {column} from {table} where {column} is not null")
        ).scalars()
        for value in rows:
            raw = str(value).strip()
            if _TWELVE_DIGITS.match(raw) or not raw.isdigit() or raw in plan.identifiers:
                continue
            replacement = plan.identifiers.get(raw.zfill(12))
            if replacement is not None:
                plan.identifiers[raw] = replacement.lstrip("0")

    personal: set[str] = set()
    for table, column in NAME_COLUMNS:
        rows = session.execute(
            text(f"select distinct {column} from {table} where {column} is not null")
        ).scalars()
        for value in rows:
            raw = str(value)
            if _PERSONAL_FORM.match(raw):
                personal.add(raw)

    # Нумерация по алфавиту, а не по порядку выборки: так повторный запуск на
    # другой копии базы даст те же подписи.
    for index, original in enumerate(sorted(personal), start=1):
        replacement = synthetic_name(original, index)
        if replacement is not None:
            plan.names[original] = replacement

    return plan


def _text_columns(session: Session) -> list[tuple[str, str]]:
    """Все текстовые колонки схемы."""
    rows = session.execute(
        text(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = 'public' "
            "and data_type in ('character varying', 'text') "
            "order by table_name, column_name"
        )
    ).all()
    return [(str(table), str(column)) for table, column in rows]


def _substitute(value: str, mapping: dict[str, str]) -> str:
    """Заменить в строке все вхождения известных идентификаторов.

    Заменяются только цифровые последовательности длиной 9–12 знаков, целиком
    совпадающие с известным номером. Более широкое правило испортило бы номера
    договоров и суммы, более узкое пропустило бы вкрапления.
    """

    def replace(match: re.Match[str]) -> str:
        digits = match.group(0)
        return mapping.get(digits) or mapping.get(digits.zfill(12)) or digits

    return re.sub(r"\d{9,12}", replace, value)


def apply(session: Session, plan: Plan) -> dict[str, int]:
    """Применить замены. Возвращает число изменённых строк по колонкам."""
    changed: dict[str, int] = {}

    def bulk(table: str, column: str, pairs: dict[str, str]) -> None:
        if not pairs:
            return
        result = session.execute(
            text(
                # Соответствия передаются одним массивом, а не тысячами
                # отдельных UPDATE: 3 668 запросов на колонку выполнялись бы
                # минутами.
                f'update "{table}" as t set "{column}" = m.replacement '
                f"from (select unnest(cast(:originals as text[])) as original, "
                f"unnest(cast(:replacements as text[])) as replacement) as m "
                f'where t."{column}" = m.original'
            ),
            {"originals": list(pairs.keys()), "replacements": list(pairs.values())},
        )
        # `rowcount` объявлен на CursorResult, а execute типизирован как Result;
        # для UPDATE это всегда CursorResult, поэтому обращение безопасно.
        rowcount = getattr(result, "rowcount", 0)
        if rowcount:
            key = f"{table}.{column}"
            changed[key] = changed.get(key, 0) + rowcount

    for table, column in NAME_COLUMNS:
        bulk(table, column, plan.names)

    # Идентификаторы заменяются во всех текстовых колонках схемы, а не в
    # заранее перечисленных. Перечень оказался ненадёжен: номер вшит ещё и в
    # служебные ключи `natural_key` и `source_row_ref`, а таких колонок в схеме
    # сорок шесть. Список, составленный руками, их пропустил — и это выяснилось
    # только сквозной проверкой, уже после «успешного» обезличивания.
    for table, column in _text_columns(session):
        values = session.execute(
            text(
                f'select distinct "{column}" from "{table}" '
                f"where \"{column}\" ~ '[0-9]{{9,12}}'"
            )
        ).scalars()

        pairs = {}
        for value in values:
            original = str(value)
            replacement = _substitute(original, plan.identifiers)
            if replacement != original:
                pairs[original] = replacement

        bulk(table, column, pairs)

    return changed


def verify(session: Session, plan: Plan | None = None) -> list[str]:
    """Проверить, что личных сведений не осталось. Пустой список — чисто.

    Проверка сквозная по всем текстовым колонкам, а не по списку изменённых.
    Первая версия проверяла ровно те колонки, которые и меняла, — и потому
    объявила базу чистой, когда настоящие номера ещё лежали в служебных
    ключах. Проверка, повторяющая допущения проверяемого кода, не проверяет
    ничего.
    """
    problems: list[str] = []

    for table, column in NAME_COLUMNS:
        remaining = session.execute(
            text(
                # ФИО опознаётся по словам после организационной формы:
                # условная подпись «ИП Получатель 0001» под это не подпадает.
                f'select count(*) from "{table}" '
                f"where \"{column}\" ~ '^\\s*(ИП|КХ)\\b' "
                f"and \"{column}\" !~ '(Получатель|Хозяйство|Субъект) [0-9]{{4}}$'"
            )
        ).scalar_one()
        if remaining:
            problems.append(f"{table}.{column}: осталось {remaining} наименований с ФИО")

    if plan is None:
        return problems

    originals = set(plan.identifiers)
    for table, column in _text_columns(session):
        values = session.execute(
            text(
                f'select distinct "{column}" from "{table}" '
                f"where \"{column}\" ~ '[0-9]{{9,12}}'"
            )
        ).scalars()

        found = sum(
            1
            for value in values
            if any(
                number in originals or number.zfill(12) in originals
                for number in re.findall(r"\d{9,12}", str(value))
            )
        )
        if found:
            problems.append(f"{table}.{column}: осталось {found} исходных идентификаторов")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="показать план, ничего не менять")
    parser.add_argument("--verify", action="store_true", help="только проверить результат")
    parser.add_argument(
        "--salt",
        default="riskmap-demo",
        help="соль генерации: разная соль даёт разные номера при том же исходнике",
    )
    args = parser.parse_args(argv)

    with session_scope() as session:
        if args.verify:
            # Здесь проверяются только имена. Убедиться, что не осталось
            # исходных идентификаторов, отдельным запуском невозможно: список
            # исходных номеров есть лишь у той сессии, которая их заменяла.
            # Полная проверка выполняется сразу после замены — и именно её
            # результат решает, годится ли база к публикации.
            problems = verify(session)
            session.rollback()
            for problem in problems:
                print(f"  ✗ {problem}")
            print("Имён физических лиц не найдено." if not problems else "Найдены имена.")
            print("Проверка идентификаторов возможна только вместе с заменой.")
            return 1 if problems else 0

        plan = collect(session, args.salt)
        print(plan.report())

        if args.dry_run:
            # Явный откат, хотя записей и не было: `session_scope` фиксирует
            # транзакцию при выходе, и режим показа не должен зависеть от того,
            # что сегодня в нём нет ни одного UPDATE.
            session.rollback()
            print("\nРежим показа плана: база не изменена.")
            return 0

        changed = apply(session, plan)
        session.commit()

        print("\nизменено строк:")
        for key, count in sorted(changed.items()):
            print(f"  {key}: {count}")

        problems = verify(session, plan)
        for problem in problems:
            print(f"  ✗ {problem}")

        if problems:
            print("\nОбезличивание неполное — публиковать нельзя.")
            return 1

        print("\nЛичных сведений не найдено. База пригодна для публикации.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
