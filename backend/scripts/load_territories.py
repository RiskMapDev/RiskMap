"""Загрузка справочника территорий в PostGIS.

    python -m scripts.load_territories            # записать
    python -m scripts.load_territories --dry-run  # показать, ничего не записывая

Сухой прогон выполняет ровно те же вставки и те же проверки PostGIS, что и
обычный, и в конце откатывает транзакцию. Это дороже, чем «предсказать» план по
файлам, но только так отчёт показывает настоящий результат: расхождение площадей,
починку геометрий и итог контрольных сумм нельзя узнать, не выполнив запросы.

Возвращаемый код: 0 — успех, 1 — есть замечания уровня ERROR, 2 — импорт упал.
Ненулевой код при ошибках качества нужен затем, чтобы запуск из планировщика не
считался успешным только потому, что скрипт не упал.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings
from app.db.models.source import IssueSeverity
from app.db.session import session_scope
from app.importers.territories import LoadReport, load_territories


def _print_report(report: LoadReport) -> None:
    print(report.summary_ru())

    population = report.reconciliation.get("population", {})
    if population:
        print("\nКонтроль населения:")
        status = "сходится" if population["all_columns_match"] else "РАСХОЖДЕНИЕ"
        print(f"  сумма {population['units_count']} единиц против итога области: {status}")
        for column, item in population["per_column"].items():
            mark = "=" if item["matches"] else "≠"
            print(f"    {column:<14} {item['units_sum']:>12,} {mark} {item['oblast']:>12,}")
        print(
            f"  мужчины + женщины = всё население: "
            f"{'сходится' if not population['gender_mismatches'] else 'РАСХОЖДЕНИЕ'}"
        )
        print(
            f"  город + село = всё население: "
            f"{'сходится' if not population['settlement_mismatches'] else 'РАСХОЖДЕНИЕ'}"
        )

    coverage = report.reconciliation.get("geometry_coverage", {})
    if coverage:
        print("\nПокрытие области единицами второго уровня:")
        print(
            f"  объединение 11 единиц {coverage['units_union_km2']:,} км² против "
            f"полигона области {coverage['oblast_polygon_km2']:,} км² "
            f"({coverage['delta_pct']:+.4f} %)"
        )

    if report.ambiguous_aliases:
        print("\nНеоднозначные написания (автосвязывание по ним запрещено):")
        for name in report.ambiguous_aliases:
            print(f"  {name}")
    else:
        print("\nНеоднозначных написаний нет: каждое название ведёт к одной территории.")

    if report.issues:
        print(f"\nЗамечания к качеству данных ({len(report.issues)}):")
        for severity, code, message in report.issues:
            print(f"  [{severity}] {code}: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="выполнить и откатить: показать результат, ничего не записав",
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--source-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    data_dir = args.data_dir or settings.data_dir
    source_dir = args.source_dir or settings.source_data_dir

    try:
        with session_scope() as session:
            report = load_territories(
                session, data_dir=data_dir, source_dir=source_dir, dry_run=args.dry_run
            )
    # CLI обязан объяснить отказ по-человечески, а не отдать трейс: сообщения
    # про несовпавший SHA-256 или пропавший файл адресованы оператору импорта.
    except Exception as error:
        print(f"Импорт не выполнен: {error}", file=sys.stderr)
        return 2

    _print_report(report)

    errors = [item for item in report.issues if item[0] == str(IssueSeverity.ERROR)]
    if errors:
        print(f"\nЗамечаний уровня ERROR: {len(errors)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
