"""Импорт слоя «Субсидии и господдержка» (ТЗ п.8.5) из Excel аналитиков.

Один прогон = полный пересчёт: читает Excel с выплатами субсидий, считает
риск-индикаторы по каждому получателю (ТЗ п.9.2), пишет в БД:

    ThematicLayer  — 1 запись слоя (subsidies), создаётся при первом запуске
    GeoObject      — 1 запись на ПОЛУЧАТЕЛЯ (не на выплату), ключ = БИН/ИИН
    RiskFactor     — 5 записей на получателя, расшифровка risk_score (ТЗ п.14)
    ImportBatch    — журнал прогона: сколько строк, сколько пропущено и почему

Идемпотентно: повторный запуск обновляет объекты по (layer, external_id),
факторы риска пересоздаёт. Дублей не будет.

Запуск:
    python manage.py import_subsidies --file /path/subsidies.xlsx --password 0101
    python manage.py import_subsidies --file /path/subsidies.xlsx --dry-run

Зависимости (добавить в requirements.txt):
    pandas, openpyxl, msoffcrypto-tool (последнее — только если файл под паролем)

ВАЖНО про территории: в БД лежат 11 территорий ТЕКУЩЕЙ Алматинской области
(9 районов + города Алатау и Конаев). В файле аналитиков — 24 названия из
СТАРОЙ области (до реформы 2022). Несопоставленные районы (Жетысу: Панфиловский,
Талдыкорган и т.д., и чужие области: Кордайский, Мойынкумский) не импортируются,
а попадают в ImportBatch.error_log. Это ~16% суммы — вне зоны MVP.
"""

from __future__ import annotations

import io
import math
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from territories.analytics import risk_level_for
from territories.models import (
    GeoObject,
    ImportBatch,
    RiskFactor,
    ThematicLayer,
    Territory,
)

# --------------------------------------------------------------------------
# Конфигурация слоя и модели риска
# --------------------------------------------------------------------------

LAYER_CODE = "subsidies"
LAYER_NAME = "Субсидии и господдержка"
LAYER_COLOR = "#8B5CF6"
SOURCE_SYSTEM = "subsidies_xlsx"
OBLAST_NAME = "Алматинская область"

# Веса индикаторов (Σ = 1.0). Меняются только здесь — расшифровка вклада
# каждого индикатора пишется в RiskFactor, поэтому пересчёт всегда прозрачен.
INDICATORS = [
    ("concentration", "Концентрация поддержки у получателя", Decimal("0.30")),
    ("repeat", "Повторное/множественное финансирование", Decimal("0.15")),
    ("affiliation", "Аффилированность (общий руководитель)", Decimal("0.20")),
    ("process_anomaly", "Процессные аномалии (выплата раньше решения)", Decimal("0.20")),
    ("amount_outlier", "Выбросы сумм против медианы вид×программа", Decimal("0.15")),
]
WEIGHTS = {code: float(w) for code, _, w in INDICATORS}

# risk_level_for (пороги уровней, ТЗ п.7.3) импортирован из
# territories.analytics — единый источник, общий с API-эндпоинтами.

# Параметры нормировки индикаторов в [0;1] — вынесены в константы,
# чтобы аналитик мог их калибровать без правки формул.
CONC_FLOOR, CONC_CEIL = 0.05, 0.50   # доля в районе
CONC_OBLAST_CEIL = 0.10              # доля в области
REPEAT_PROGRAMS_CEIL = 6             # число разных программ
REPEAT_PAYMENTS_CEIL = 100           # число выплат (по ln-шкале от 3)
AFFIL_CEIL = 3                       # получателей у одного руководителя
ANOMALY_CEIL = 0.30                  # доля аномальных выплат
OUTLIER_CEIL = 0.20                  # доля выплат-выбросов
GAP_HIGH_DAYS = 170                  # p95 лага «решение → выплата»

REQUIRED_COLUMNS = [
    "DistrictName", "AnimalType", "EnterpriseXin", "EnterpriseName",
    "EnterpriseDirector", "SubsidiesName", "PositiveDecisionDate",
    "LocalPaymentDate", "RepublicPaidBudget", "LocalPaidBudget",
]

# Названия районов в файле аналитиков не совпадают с name_ru в БД
# («Қонаев Г.А.» → «Конаев»). Сопоставляем по нормализованному имени.
KZ_TRANSLIT = str.maketrans({
    "қ": "к", "ә": "а", "ө": "о", "ұ": "у", "ү": "у",
    "і": "и", "ң": "н", "ғ": "г", "һ": "х", "ё": "е",
})


def normalize_name(value: str) -> str:
    """«Қонаев Г.А.» и «Конаев» → «конаев». Ключ сопоставления районов."""
    s = str(value or "").strip().lower().translate(KZ_TRANSLIT)
    for junk in ("район", "ауданы", "г.а.", "г.а", "гa", "қаласы", "каласы"):
        s = s.replace(junk, " ")
    return " ".join(s.split())


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------
# Чтение файла
# --------------------------------------------------------------------------

# Лист с сырыми данными и «якорные» колонки для поиска строки заголовков.
DEFAULT_SHEET = "Данные"
HEADER_ANCHORS = ("DistrictName", "EnterpriseXin")


def _pick_sheet(xl, sheet):
    """Выбирает лист: явный аргумент -> «Данные» -> первый лист."""
    if sheet:
        if sheet not in xl.sheet_names:
            raise CommandError(
                f"Листа «{sheet}» нет. Доступны: {', '.join(xl.sheet_names)}"
            )
        return sheet
    if DEFAULT_SHEET in xl.sheet_names:
        return DEFAULT_SHEET
    return xl.sheet_names[0]


def _detect_header_row(xl, sheet):
    """Ищет строку заголовков по «якорным» колонкам (файл аналитиков может
    иметь merged-заголовок сверху, из-за чего header не на строке 0)."""
    import pandas as pd

    probe = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=str, nrows=15)
    for i in range(len(probe)):
        values = {str(v).strip() for v in probe.iloc[i].tolist()}
        if all(anchor in values for anchor in HEADER_ANCHORS):
            return i
    return 0


def load_dataframe(path: Path, password: str | None, sheet: str | None = None):
    """Читает Excel аналитиков. При наличии пароля снимает шифрование в память.

    Устойчив к формату «книги с расчётом»: сырьё лежит на листе «Данные»,
    заголовки — не обязательно на первой строке (сверху бывает merged-титул).
    Лист и строку заголовков определяем автоматически.
    """
    import pandas as pd

    handle: io.BytesIO | Path = path
    if password:
        try:
            import msoffcrypto
        except ImportError as exc:
            raise CommandError(
                "Файл под паролем, нужен msoffcrypto-tool: pip install msoffcrypto-tool"
            ) from exc
        buffer = io.BytesIO()
        with path.open("rb") as fh:
            office = msoffcrypto.OfficeFile(fh)
            office.load_key(password=password)
            office.decrypt(buffer)
        buffer.seek(0)
        handle = buffer

    xl = pd.ExcelFile(handle, engine="openpyxl")
    target = _pick_sheet(xl, sheet)
    header_row = _detect_header_row(xl, target)

    df = pd.read_excel(xl, sheet_name=target, header=header_row, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CommandError(
            f"На листе «{target}» нет обязательных колонок: {', '.join(missing)}"
        )
    return df


def prepare(df):
    """Приводит типы, считает выплату, лаг и флаги аномалий по каждой строке."""
    import numpy as np
    import pandas as pd

    for col in ("RepublicPaidBudget", "LocalPaidBudget"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["paid"] = df[["RepublicPaidBudget", "LocalPaidBudget"]].sum(axis=1, min_count=1).fillna(0)

    df["decision_at"] = pd.to_datetime(df["PositiveDecisionDate"], errors="coerce")
    df["paid_at"] = pd.to_datetime(df["LocalPaymentDate"], errors="coerce")
    df["gap_days"] = (df["paid_at"] - df["decision_at"]).dt.days
    df["year"] = df["paid_at"].dt.year

    # Аномалия процесса: выплата раньше положительного решения либо
    # ненормально длинный лаг. Первое — прямой красный флаг контроля.
    df["is_anomaly"] = (df["gap_days"] < 0) | (df["gap_days"] > GAP_HIGH_DAYS)

    # Выброс суммы: робастный порог Q3 + 3·IQR внутри группы «вид × программа».
    # Группы меньше 20 строк пропускаем — статистики не хватает.
    df["grp"] = df["AnimalType"].astype(str) + " | " + df["SubsidiesName"].astype(str)

    def threshold(s):
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        return q3 + 3 * (q3 - q1) if s.size >= 20 else np.inf

    df["is_outlier"] = df["paid"] > df.groupby("grp")["paid"].transform(threshold)
    df["norm_district"] = df["DistrictName"].map(normalize_name)
    return df


# --------------------------------------------------------------------------
# Расчёт риска
# --------------------------------------------------------------------------

def compute_scores(scope) -> dict:
    """Считает s1..s5 и R по каждому получателю на переданном срезе данных.

    Вызывается и на всём периоде (итоговый risk_score объекта), и на срезе
    каждого года (attributes.by_year[...] — под фильтр периода на фронте).
    Возвращает {xin: {...}}.
    """
    import numpy as np

    if scope.empty:
        return {}

    district_total = scope.groupby("norm_district")["paid"].sum()
    oblast_total = scope["paid"].sum() or 1.0

    # Аффилированность: сколько РАЗНЫХ получателей у одного руководителя.
    # Пустые ФИО не группируем — иначе все «безымянные» слиплись бы в кластер.
    directors = scope.assign(d=scope["EnterpriseDirector"].astype(str).str.strip().str.upper())
    named = directors[~directors["d"].isin(["", "NAN", "NONE"])]
    per_director = named.groupby("d")["EnterpriseXin"].nunique()

    grouped = scope.groupby("EnterpriseXin")
    result = {}

    for xin, g in grouped:
        paid = float(g["paid"].sum())
        payments = int(len(g))
        programs = int(g["SubsidiesName"].nunique())

        # Район получателя — тот, где у него больше всего денег.
        district = g.groupby("norm_district")["paid"].sum().idxmax()
        share_district = paid / float(district_total.get(district, 0) or 1.0)
        share_oblast = paid / float(oblast_total)

        director = str(g["EnterpriseDirector"].iloc[0] or "").strip().upper()
        cluster = int(per_director.get(director, 1)) if director not in ("", "NAN", "NONE") else 1

        anomaly_share = float(g["is_anomaly"].sum()) / payments
        outlier_share = float(g["is_outlier"].sum()) / payments

        s1 = max(
            clamp((share_district - CONC_FLOOR) / (CONC_CEIL - CONC_FLOOR)),
            clamp(share_oblast / CONC_OBLAST_CEIL),
        )
        s2 = 0.5 * clamp((programs - 1) / (REPEAT_PROGRAMS_CEIL - 1)) + 0.5 * clamp(
            (math.log(payments) - math.log(3)) / (math.log(REPEAT_PAYMENTS_CEIL) - math.log(3))
        )
        s3 = clamp((cluster - 1) / (AFFIL_CEIL - 1))
        s4 = clamp(anomaly_share / ANOMALY_CEIL)
        s5 = clamp(outlier_share / OUTLIER_CEIL)

        scores = {
            "concentration": s1, "repeat": s2, "affiliation": s3,
            "process_anomaly": s4, "amount_outlier": s5,
        }
        raw = {
            "concentration": share_district, "repeat": float(programs),
            "affiliation": float(cluster), "process_anomaly": anomaly_share,
            "amount_outlier": outlier_share,
        }
        r = 100.0 * sum(WEIGHTS[k] * v for k, v in scores.items())

        result[str(xin)] = {
            "name": str(g["EnterpriseName"].iloc[0]),
            "director": str(g["EnterpriseDirector"].iloc[0] or ""),
            "district": district,
            "paid": paid,
            "payments": payments,
            "programs": programs,
            "programs_list": sorted({str(x) for x in g["SubsidiesName"].dropna().unique()}),
            "animal_types": sorted({str(x) for x in g["AnimalType"].dropna().unique()}),
            "share_district": share_district,
            "share_oblast": share_oblast,
            "cluster": cluster,
            "anomaly_share": anomaly_share,
            "outlier_share": outlier_share,
            "scores": scores,
            "raw": raw,
            "risk_score": round(r, 2),
            "risk_level": risk_level_for(r),
            "first_payment": _iso(g["paid_at"].min()),
            "last_payment": _iso(g["paid_at"].max()),
        }
    return result


def _iso(value):
    import pandas as pd
    return None if pd.isna(value) else value.date().isoformat()


# --------------------------------------------------------------------------
# Команда
# --------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Импортирует субсидии из Excel, считает риск по получателям (ТЗ 8.5/9.2/14)"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Путь к Excel аналитиков")
        parser.add_argument("--password", default=None, help="Пароль Excel, если зашифрован")
        parser.add_argument("--source-name", default="Субсидии (файл аналитиков)")
        parser.add_argument("--user", default=None, help="username, кто загрузил")
        parser.add_argument(
            "--sheet", default=None,
            help="Имя листа с сырьём (по умолчанию «Данные», иначе первый)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Не писать в БД")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"Файл не найден: {path}")

        self.stdout.write("Чтение файла…")
        df = prepare(load_dataframe(path, options["password"], options["sheet"]))
        total_rows = len(df)

        # --- сопоставление районов с Territory ---
        try:
            oblast = Territory.objects.get(level=Territory.Level.OBLAST, name_ru=OBLAST_NAME)
        except Territory.DoesNotExist as exc:
            raise CommandError(
                f"Нет области «{OBLAST_NAME}». Сначала: python manage.py load_boundaries"
            ) from exc

        territories = {
            normalize_name(t.name_ru): t
            for t in Territory.objects.filter(parent=oblast)
        }
        if not territories:
            raise CommandError("У области нет районов. Сначала: python manage.py load_boundaries")

        known = set(territories)
        matched = df[df["norm_district"].isin(known)].copy()
        skipped = df[~df["norm_district"].isin(known)]

        error_log = []
        if not skipped.empty:
            # dropna=False — иначе строки с пустым DistrictName (в файле их ~96)
            # попали бы в error_rows, но не в протокол, и причина потерялась бы.
            for name, g in skipped.groupby("DistrictName", dropna=False):
                is_empty = not (isinstance(name, str) and name.strip())
                error_log.append({
                    "reason": "district_empty" if is_empty else "district_not_in_current_oblast",
                    "district": "(пусто)" if is_empty else str(name),
                    "rows": int(len(g)),
                    "paid": float(g["paid"].sum()),
                })
        self.stdout.write(
            f"Строк: {total_rows} | сопоставлено: {len(matched)} | "
            f"пропущено (не текущая область): {len(skipped)}"
        )
        if matched.empty:
            raise CommandError("Ни одна строка не сопоставилась с районами области.")

        # --- расчёт: весь период + разрез по годам (под фильтр периода) ---
        self.stdout.write("Расчёт риск-индикаторов…")
        overall = compute_scores(matched)
        by_year_scores = {}
        for year in sorted(int(y) for y in matched["year"].dropna().unique()):
            by_year_scores[year] = compute_scores(matched[matched["year"] == year])
        self.stdout.write(
            f"Получателей: {len(overall)} | годы: {', '.join(map(str, by_year_scores))}"
        )

        if options["dry_run"]:
            self._report_preview(overall)
            self.stdout.write(self.style.WARNING("dry-run: в БД ничего не записано."))
            return

        user = self._resolve_user(options["user"])

        with transaction.atomic():
            layer, _ = ThematicLayer.objects.get_or_create(
                code=LAYER_CODE,
                defaults={
                    "name_ru": LAYER_NAME,
                    "color_hex": LAYER_COLOR,
                    "description": "Субсидии и меры господдержки (ТЗ п.8.5)",
                    "sort_order": 10,
                },
            )
            batch = ImportBatch.objects.create(
                file_name=path.name,
                source_name=options["source_name"],
                layer=layer,
                status=ImportBatch.Status.PENDING,
                total_rows=total_rows,
                imported_by=user,
            )

            created, updated = self._write_objects(layer, territories, overall, by_year_scores)

            batch.imported_rows = len(matched)
            batch.error_rows = len(skipped)
            batch.error_log = error_log
            batch.status = ImportBatch.Status.DONE
            batch.save(update_fields=["imported_rows", "error_rows", "error_log", "status"])

        self.stdout.write(self.style.SUCCESS(
            f"Готово. Объектов создано: {created}, обновлено: {updated}. "
            f"ImportBatch #{batch.id}"
        ))

    # ----------------------------------------------------------------------

    def _resolve_user(self, username):
        if not username:
            return None
        from django.contrib.auth import get_user_model
        try:
            return get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist:
            self.stdout.write(self.style.WARNING(f"Пользователь {username} не найден"))
            return None

    def _write_objects(self, layer, territories, overall, by_year_scores):
        """Пишет GeoObject + RiskFactor. Ключ идемпотентности — (layer, БИН)."""
        now = timezone.now()
        created = updated = 0
        # Кэш точек: у субсидий нет координат получателя — ставим точку
        # на поверхности района и честно помечаем это в attributes.
        centroids: dict[int, Point] = {}

        for xin, data in overall.items():
            territory = territories[data["district"]]
            if territory.id not in centroids:
                centroids[territory.id] = territory.geometry.point_on_surface

            by_year = {}
            for year, scores in by_year_scores.items():
                row = scores.get(xin)
                if row:
                    by_year[str(year)] = {
                        "paid": round(row["paid"], 2),
                        "payments": row["payments"],
                        "risk_score": row["risk_score"],
                        "risk_level": row["risk_level"],
                    }

            attributes = {
                "bin": xin,
                "director": data["director"],
                "paid_total": round(data["paid"], 2),
                "payments_count": data["payments"],
                "programs_count": data["programs"],
                "programs": data["programs_list"],
                "animal_types": data["animal_types"],
                "share_district": round(data["share_district"], 4),
                "share_oblast": round(data["share_oblast"], 5),
                "affiliation_cluster_size": data["cluster"],
                "anomaly_share": round(data["anomaly_share"], 4),
                "outlier_share": round(data["outlier_share"], 4),
                "first_payment": data["first_payment"],
                "last_payment": data["last_payment"],
                "by_year": by_year,
                # ТЗ п.15.3 — маркировка неточной геопривязки.
                "geo_precision": "district_centroid",
                "district_source_name": data["district"],
            }

            obj, is_new = GeoObject.objects.update_or_create(
                layer=layer,
                external_id=str(xin),
                defaults={
                    "territory": territory,
                    "name": data["name"][:500],
                    "source_system": SOURCE_SYSTEM,
                    "imported_at": now,
                    "attributes": attributes,
                    "geometry": centroids[territory.id],
                    "risk_score": Decimal(str(data["risk_score"])),
                    "risk_level": data["risk_level"],
                },
            )
            created, updated = (created + 1, updated) if is_new else (created, updated + 1)

            # Расшифровка расчёта пересоздаётся целиком — веса могли измениться.
            obj.risk_factors.all().delete()
            RiskFactor.objects.bulk_create([
                RiskFactor(
                    geo_object=obj,
                    indicator_code=code,
                    indicator_name=name,
                    raw_value=Decimal(str(round(data["raw"][code], 4))),
                    weight=weight,
                    contribution=Decimal(str(round(100 * float(weight) * data["scores"][code], 2))),
                )
                for code, name, weight in INDICATORS
            ])
        return created, updated

    def _report_preview(self, overall):
        top = sorted(overall.items(), key=lambda kv: -kv[1]["risk_score"])[:10]
        self.stdout.write("\nТОП-10 по коэффициенту риска:")
        for xin, d in top:
            self.stdout.write(
                f"  R={d['risk_score']:5.1f} {d['risk_level']:8s} | {d['name'][:34]:34s} "
                f"| {d['paid']:>15,.0f} ₸"
            )
