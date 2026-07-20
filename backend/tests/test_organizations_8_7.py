"""Тесты слоя 8.7 — хозяйствующие субъекты (организации).

Слой 8.7 — самый честный и самый неудобный слой проекта: **модель обеспечена
данными на 41 %**. Из тринадцати индикаторов ТЗ 9.4 считаются пять (юридический
факт A1 без веса и четыре весовых — B3, B5, B6, B8), что даёт 45 баллов веса
из 110. Максимальная полнота во всей выборке — 40.9 %, ниже порога серого в
50 %. Отсюда строгий результат: серых 3645, критических 23 — и это не ошибка
расчёта, а состояние источников.

Что здесь доказывается:

* неподключённые индикаторы видны как «не измерено» **с причиной**, а не
  молча отсутствуют — иначе низкая полнота ничем не объясняется;
* предварительный балл показывается рядом с серым уровнем, но официальным
  уровнем остаётся серый: в фильтрах и агрегатах такой объект относится к
  «нет данных». Это решение заказчика, и тест обязан падать при попытке
  подменить уровень предварительным;
* категория A сильнее и балла, и нехватки данных: три организации из 23 имеют
  балл 0 и всё равно критические;
* ведущие нули БИН восстановлены — 763 значения из 3668 потеряли их при
  выгрузке, и джойн без `zfill(12)` теряет пятую часть связей;
* отсутствие данных нигде не превращается в ноль.

Golden-тесты сверяются с контрольными значениями аудита
(`docs/audit/03-sloi-8-5-8-6-8-7.md`, раздел 3.7). Расхождений нет: все 3668
строк воспроизводятся построчно.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import NamedTuple

import pytest

from app.core.config import get_settings
from app.db.models.organization import Organization, TerritoryStatus
from app.importers.organizations_8_7 import (
    BIN_LENGTH,
    EXPECTED_ROW_COUNT,
    MEASURED_CODES,
    MODEL,
    OrganizationRow,
    bin_index,
    bin_leading_zeros_lost,
    indicator_values,
    normalize_bin,
    read_organizations_from_source_dir,
)
from app.risk.core import IndicatorValue, RiskLevel, RiskModelSpec, RiskResult, aggregate_levels
from app.risk.layers.organizations import (
    CATEGORY_A_CODES,
    MIN_COMPLETENESS_8_7,
    NOT_CONNECTED,
    ORGANIZATION_INDICATORS,
    ORGANIZATION_MODEL,
    THRESHOLDS_8_7,
    b3_value,
    b5_value,
    b6_value,
    b8_value,
    category_a_fact,
    category_a_override,
    evaluate_organization,
    preliminary_level,
    unmeasured,
)

# --- Контрольные значения аудита ---------------------------------------------

#: БИН → (балл книги, предварительный уровень). Раздел 3.7, «5 эталонных строк».
ЭТАЛОННЫЕ_ОРГАНИЗАЦИИ: dict[str, tuple[float, RiskLevel]] = {
    "170640011921": (93.3, RiskLevel.CRITICAL),
    "090340012684": (88.6, RiskLevel.CRITICAL),
    "010440001281": (62.9, RiskLevel.HIGH),
    "070340007515": (42.9, RiskLevel.MEDIUM),
    "190440018905": (0.0, RiskLevel.LOW),
}

#: Официальное распределение по ТЗ 7.3. Ни одного низкого, среднего и высокого.
СТРОГОЕ_РАСПРЕДЕЛЕНИЕ: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 0,
    RiskLevel.HIGH: 0,
    RiskLevel.CRITICAL: 23,
    RiskLevel.UNKNOWN: 3645,
}

#: Предварительное распределение — то, что балл «подсказывает». Официальным
#: не является ни при каких условиях.
ПРЕДВАРИТЕЛЬНОЕ_РАСПРЕДЕЛЕНИЕ: dict[RiskLevel, int] = {
    RiskLevel.LOW: 1147,
    RiskLevel.MEDIUM: 2211,
    RiskLevel.HIGH: 278,
    RiskLevel.CRITICAL: 32,
}

#: Три организации категории A с баллом 0 — эталон жёсткого переопределения
#: (проверочный пример 3 листа «Формула»).
КАТЕГОРИЯ_A_С_НУЛЁМ: frozenset[str] = frozenset(
    {"140340003568", "190940015681", "171140000524"}
)

НЕПОДКЛЮЧЁННЫЕ_КОДЫ: frozenset[str] = frozenset({"A2", "A3", "A4", "B1", "B2", "B4", "B7", "B9"})

УРОВНИ_КНИГИ: dict[str, RiskLevel] = {
    "низкий": RiskLevel.LOW,
    "средний": RiskLevel.MEDIUM,
    "высокий": RiskLevel.HIGH,
    "критический": RiskLevel.CRITICAL,
    "серый (недостаточно данных)": RiskLevel.UNKNOWN,
}


# --- Вспомогательное ----------------------------------------------------------


def значения(
    *,
    b3: float | None = 0.0,
    b5: float | None = 0.0,
    b6: float | None = 0.0,
    b8: float | None = 0.0,
    категория_a: bool | None = False,
) -> dict[str, IndicatorValue]:
    """Полный набор из тринадцати индикаторов для одной организации.

    Неподключённые передаются явно — ровно так же, как это делает импортёр:
    без них причина «нет публичного API» не дошла бы до карточки риска.
    """
    набор: dict[str, IndicatorValue] = {
        "A1": category_a_fact("A1", confirmed=категория_a),
        "A2": category_a_fact("A2", confirmed=None),
        "A3": category_a_fact("A3", confirmed=None),
        "A4": category_a_fact("A4", confirmed=None),
        "B3": IndicatorValue(code="B3", value=b3),
        "B5": IndicatorValue(code="B5", value=b5),
        "B6": IndicatorValue(code="B6", value=b6),
        "B8": IndicatorValue(code="B8", value=b8),
    }
    for код in ("B1", "B2", "B4", "B7", "B9"):
        набор[код] = unmeasured(код, NOT_CONNECTED)
    return набор


def организация(**поля: object) -> OrganizationRow:
    """Синтетическая строка витрины 8.7."""
    основа: dict[str, object] = {
        "row_number": 4,
        "bin": "090340012684",
        "bin_raw": "90340012684",
        "leading_zeros_restored": True,
        "name": "ТОО Пример",
        "b3_value": 0.0,
        "b5_value": 0.0,
        "b6_value": 0.0,
        "b8_value": 0.0,
        "is_category_a": False,
        "book_raw_score": 0.0,
        "book_available_weight": 45.0,
        "book_score": 0.0,
        "book_completeness_percent": 40.9,
        "book_level_preliminary": "низкий",
        "book_level_strict": "серый (недостаточно данных)",
        "book_explanation": "факторы риска не выявлены",
    }
    основа.update(поля)
    return OrganizationRow(**основа)  # type: ignore[arg-type]


class Выборка(NamedTuple):
    """Разобранная и посчитанная выборка организаций."""

    строки: tuple[OrganizationRow, ...]
    оценки: dict[str, RiskResult]


@pytest.fixture(scope="session")
def выборка() -> Выборка:
    """3668 организаций, посчитанные один раз на весь прогон."""
    try:
        строки = tuple(read_organizations_from_source_dir(get_settings().source_data_dir))
    except (FileNotFoundError, SystemExit, OSError) as exc:  # pragma: no cover — среда без книг
        pytest.skip(f"Книга слоя 8.7 недоступна: {exc}")
    оценки = {
        строка.bin: evaluate_organization(indicator_values(строка)) for строка in строки
    }
    return Выборка(строки, оценки)


# --- Модель и её обеспеченность ----------------------------------------------


class TestОбеспеченностьМодели:
    """41 % — это число, а не оценка. Оно должно быть проверяемым."""

    def test_trinadtsat_indikatorov_tz_9_4(self) -> None:
        assert len(ORGANIZATION_INDICATORS) == 13
        коды = [индикатор.code for индикатор in ORGANIZATION_INDICATORS]
        assert коды == [
            *("A1", "A2", "A3", "A4"),
            *("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"),
        ]

    def test_polnyy_ves_metodiki_110(self) -> None:
        """Категория A весит ноль: её признаки не складываются с баллами."""
        assert ORGANIZATION_MODEL.total_weight == pytest.approx(110.0)
        assert sum(и.weight for и in ORGANIZATION_INDICATORS if и.code in CATEGORY_A_CODES) == 0.0

    def test_podklyucheno_45_iz_110(self) -> None:
        assert ORGANIZATION_MODEL.available_total_weight == pytest.approx(45.0)
        доля = ORGANIZATION_MODEL.available_total_weight / ORGANIZATION_MODEL.total_weight
        assert доля == pytest.approx(0.409, abs=0.001)

    def test_rabotayut_rovno_chetyre_vesovykh_indikatora(self) -> None:
        """B3 (10) + B5 (15) + B6 (10) + B8 (10) = 45."""
        рабочие = {и.code: и.weight for и in ORGANIZATION_INDICATORS if и.available and и.weight}
        assert рабочие == {"B3": 10.0, "B5": 15.0, "B6": 10.0, "B8": 10.0}
        assert set(MEASURED_CODES) == set(рабочие)

    def test_devyat_indikatorov_ne_podklyucheny(self) -> None:
        неподключённые = {и.code for и in ORGANIZATION_INDICATORS if not и.available}
        assert неподключённые == НЕПОДКЛЮЧЁННЫЕ_КОДЫ
        assert len(неподключённые) == 8
        # Плюс A1: источник подключён, но в баллах он не участвует — считать
        # его «работающим весовым» индикатором нельзя.
        assert ORGANIZATION_MODEL.indicator("A1").available is True
        assert ORGANIZATION_MODEL.indicator("A1").weight == 0.0

    def test_dazhe_polnyy_nabor_dannykh_ne_daet_poroga_serogo(self) -> None:
        """Ключевой факт слоя, выраженный неравенством.

        Даже если все подключённые источники заполнены у всех строк, полнота
        останется 40.9 % — ниже порога 50 %. Значит серым будет **каждая**
        организация, кроме переопределённых категорией A. Это следствие
        обеспеченности источниками, а не свойство конкретной выгрузки.
        """
        максимум = ORGANIZATION_MODEL.available_total_weight / ORGANIZATION_MODEL.total_weight
        assert максимум < MIN_COMPLETENESS_8_7

    def test_porogi_25_50_75_i_seryy_pri_polnote_nizhe_poloviny(self) -> None:
        assert [граница for граница, _ in THRESHOLDS_8_7] == [0.0, 25.0, 50.0, 75.0]
        assert MIN_COMPLETENESS_8_7 == 0.5
        assert ORGANIZATION_MODEL.min_completeness == 0.5

        assert ORGANIZATION_MODEL.level_for(24.999) is RiskLevel.LOW
        assert ORGANIZATION_MODEL.level_for(25.0) is RiskLevel.MEDIUM
        assert ORGANIZATION_MODEL.level_for(50.0) is RiskLevel.HIGH
        assert ORGANIZATION_MODEL.level_for(75.0) is RiskLevel.CRITICAL

    def test_importer_ssylaetsya_na_tu_zhe_model(self) -> None:
        """Одна модель — одна версия. Две копии разошлись бы при первой правке."""
        assert MODEL is ORGANIZATION_MODEL


class TestНеподключённыеИндикаторыВидны:
    """Требование ТЗ и UI: раздел «не измерено» обязателен к показу.

    Прятать неподключённые индикаторы нельзя по двум причинам, и обе
    проверяются здесь: полнота перестанет быть честной, а пользователь не
    узнает, чего именно не хватает.
    """

    def test_kazhdyy_neizmerennyy_indikator_popadaet_v_rasshifrovku(self) -> None:
        результат = evaluate_organization(значения())
        коды = [фактор.code for фактор in результат.factors]

        assert len(коды) == 13
        assert коды == [и.code for и in ORGANIZATION_INDICATORS]

    def test_u_kazhdogo_neizmerennogo_est_prichina_tekstom(self) -> None:
        """«Не измерено» без объяснения неотличимо от «забыли посчитать»."""
        результат = evaluate_organization(значения())
        неизмеренные = {ф.code: ф for ф in результат.unmeasured_factors}

        for код in НЕПОДКЛЮЧЁННЫЕ_КОДЫ:
            assert код in неизмеренные, код
            assert неизмеренные[код].note.strip(), код
            assert неизмеренные[код].effect == "не измерено", код
            assert неизмеренные[код].contribution is None, код

    def test_prichina_nazyvaet_otsutstvie_publichnogo_api(self) -> None:
        результат = evaluate_organization(значения())
        неизмеренные = {ф.code: ф for ф in результат.unmeasured_factors}

        for код in ("B1", "B2", "B4", "B7", "B9"):
            assert неизмеренные[код].note == NOT_CONNECTED
        assert "нет публичного API" in NOT_CONNECTED

    def test_istochnik_indikatora_nazvan(self) -> None:
        """Пользователь должен видеть не только «нет данных», но и откуда они
        появятся, когда источник подключат."""
        результат = evaluate_organization(значения())
        for фактор in результат.factors:
            assert фактор.source.strip(), фактор.code

    def test_esli_spryatat_neподключённые_polnota_stanet_lozhnoy(self) -> None:
        """Тот самый сценарий, ради которого неподключённые остаются в модели.

        Уберите девять неподключённых индикаторов из списка — и модель с
        четырьмя работающими отрапортует стопроцентную полноту, то есть
        объявит себя полностью обеспеченной данными. Тест держит цену этой
        ошибки на виду: 100 % против честных 40.9 %.
        """
        урезанная: RiskModelSpec = replace(
            ORGANIZATION_MODEL,
            code="8.7-organizations-урезанная",
            indicators=tuple(и for и in ORGANIZATION_INDICATORS if и.available and и.weight),
        )
        честный = evaluate_organization(значения(b3=1.0, b5=1.0, b6=1.0, b8=1.0))

        from app.risk.core import evaluate

        лживый = evaluate(
            урезанная,
            {код: IndicatorValue(code=код, value=1.0) for код in MEASURED_CODES},
        )

        assert честный.completeness == pytest.approx(0.409, abs=0.001)
        assert лживый.completeness == pytest.approx(1.0)
        assert честный.level is RiskLevel.UNKNOWN
        assert лживый.level is RiskLevel.CRITICAL


# --- Идентификаторы -----------------------------------------------------------


class TestБИН:
    """763 БИН из 3668 потеряли ведущие нули: источник хранит их числом."""

    @pytest.mark.parametrize(
        ("исходное", "ожидаемое"),
        [
            ("090340012684", "090340012684"),
            ("90340012684", "090340012684"),
            (90340012684, "090340012684"),
            ("21040006143", "021040006143"),
            ("1240000801", "001240000801"),
            ("  90340012684  ", "090340012684"),
        ],
    )
    def test_bin_vsegda_12_znakov(self, исходное: object, ожидаемое: str) -> None:
        assert normalize_bin(исходное) == ожидаемое
        assert len(normalize_bin(исходное)) == BIN_LENGTH

    def test_slishkom_dlinnoe_znachenie_ne_podrezaetsya(self) -> None:
        """13 знаков — это не БИН с опечаткой, а другая сущность.

        Молча подрезать его значит связать организацию не с той записью.
        """
        with pytest.raises(ValueError, match="длиннее"):
            normalize_bin("1234567890123")

    def test_nechislovoe_znachenie_otvergaetsya(self) -> None:
        with pytest.raises(ValueError, match="не является последовательностью цифр"):
            normalize_bin("БИН отсутствует")
        with pytest.raises(ValueError, match="не является последовательностью цифр"):
            normalize_bin("")

    def test_fakt_poteri_nuley_sokhranyaetsya(self) -> None:
        """После `zfill` уже не видно, что данные приходили испорченными.

        Отчёт о качестве данных обязан это показывать, поэтому факт
        восстановления фиксируется отдельным признаком.
        """
        assert bin_leading_zeros_lost("90340012684") is True
        assert bin_leading_zeros_lost(90340012684) is True
        assert bin_leading_zeros_lost("090340012684") is False

    def test_dubl_bin_eto_otkaz_a_ne_tikhaya_perezapis(self) -> None:
        """БИН — единственный ключ слоя. Тихая перезапись потеряла бы строку."""
        строки = [организация(row_number=4), организация(row_number=5)]
        with pytest.raises(ValueError, match="Дубль БИН"):
            bin_index(строки)

    def test_ukazatel_stroitsya_po_kanonicheskomu_bin(self) -> None:
        указатель = bin_index([организация(bin="090340012684", bin_raw="90340012684")])
        assert "090340012684" in указатель
        assert "90340012684" not in указатель


# --- Индикаторы: пустота не ноль ----------------------------------------------


class TestИндикаторыB:
    @pytest.mark.parametrize(
        ("организаций_по_адресу", "ожидаемое"),
        [(1, 0.0), (2, 0.0), (3, 0.3), (4, 0.3), (5, 0.7), (9, 0.7), (10, 1.0), (40, 1.0)],
    )
    def test_b3_massovaya_registratsiya(
        self, организаций_по_адресу: int, ожидаемое: float
    ) -> None:
        значение = b3_value(организаций_по_адресу)
        assert значение.value == pytest.approx(ожидаемое)
        assert значение.raw_value == организаций_по_адресу

    @pytest.mark.parametrize(
        ("секций_okeд", "ожидаемое"), [(1, 0.0), (2, 0.0), (3, 0.4), (4, 1.0), (7, 1.0)]
    )
    def test_b6_chislo_sektsiy_oked(self, секций_okeд: int, ожидаемое: float) -> None:
        assert b6_value(секций_okeд).value == pytest.approx(ожидаемое)

    @pytest.mark.parametrize(
        ("компаний_u_direktora", "ожидаемое"),
        [(1, 0.0), (2, 0.2), (3, 0.6), (4, 0.6), (5, 1.0), (12, 1.0)],
    )
    def test_b8_nominalnoe_rukovodstvo(
        self, компаний_u_direktora: int, ожидаемое: float
    ) -> None:
        assert b8_value(компаний_u_direktora).value == pytest.approx(ожидаемое)

    def test_b5_gradatsii(self) -> None:
        нет_активности = b5_value(no_physical_activity=True, inactive_kkm_only=False)
        только_ккм = b5_value(no_physical_activity=False, inactive_kkm_only=True)
        всё_в_порядке = b5_value(no_physical_activity=False, inactive_kkm_only=False)

        assert нет_активности.value == pytest.approx(1.0)
        assert только_ккм.value == pytest.approx(0.5)
        assert всё_в_порядке.value == pytest.approx(0.0)

    def test_b5_izmeren_esli_izvesten_khotya_by_odin_priznak(self) -> None:
        """Отрицательный ответ — такой же результат наблюдения, как и положительный."""
        частично = b5_value(no_physical_activity=False, inactive_kkm_only=None)
        assert частично.is_measured is True
        assert частично.value == pytest.approx(0.0)


class TestПустотаНеНоль:
    """Отсутствие данных нигде не превращается в ноль — ни в одном индикаторе."""

    def test_pustoy_oked_eto_ne_izmereno_a_ne_odna_sektsiya(self) -> None:
        """763 организации без сведений об ОКЭД — те самые строки, у которых
        полнота падает с 40.9 до 31.8 %."""
        значение = b6_value(None)
        assert значение.is_measured is False
        assert значение.value is None
        assert "ОКЭД" in значение.note

    def test_neizvestnyy_iin_rukovoditelya_eto_ne_izmereno(self) -> None:
        значение = b8_value(None)
        assert значение.is_measured is False
        assert "ИИН" in значение.note

    def test_neizvestnyy_adres_eto_ne_izmereno(self) -> None:
        значение = b3_value(None)
        assert значение.is_measured is False
        assert значение.value is None

    def test_b5_bez_svedeniy_voobshche_ne_izmeren(self) -> None:
        значение = b5_value(no_physical_activity=None, inactive_kkm_only=None)
        assert значение.is_measured is False
        assert "физической активности" in значение.note

    def test_neizmerennyy_b6_menyaet_znamenatel_a_ne_chislitel(self) -> None:
        """W_avail становится 35 вместо 45 — балл нормируется на доступный вес.

        Если бы пустой ОКЭД считался нулём, организация с единственным
        сработавшим признаком получила бы 33.3 вместо 42.9 и выглядела бы
        благополучнее, чем она есть.
        """
        честно = evaluate_organization(значения(b3=0.0, b5=1.0, b6=None, b8=0.0))
        ошибочно = evaluate_organization(значения(b3=0.0, b5=1.0, b6=0.0, b8=0.0))

        assert честно.available_weight == pytest.approx(35.0)
        assert честно.score == pytest.approx(42.857, abs=0.001)
        assert ошибочно.available_weight == pytest.approx(45.0)
        assert ошибочно.score == pytest.approx(33.333, abs=0.001)
        assert честно.score is not None and ошибочно.score is not None
        assert честно.score > ошибочно.score

    def test_esli_ne_izmereno_nichego_balla_net_a_ne_nol(self) -> None:
        ничего = {код: unmeasured(код) for код in ("B3", "B5", "B6", "B8")}
        ничего.update({код: category_a_fact(код, confirmed=None) for код in CATEGORY_A_CODES})
        ничего.update({код: unmeasured(код) for код in ("B1", "B2", "B4", "B7", "B9")})
        результат = evaluate_organization(ничего)

        assert результат.score is None
        assert результат.raw_score is None
        assert результат.completeness == pytest.approx(0.0)
        assert результат.level is RiskLevel.UNKNOWN

    def test_yuridicheskiy_fakt_ne_uchastvuet_v_ballakh(self) -> None:
        """Ноль здесь был бы неправильным вдвойне: он и добавил бы вес в
        знаменатель, и выдал бы «не состоит» за «не проверяли»."""
        подтверждён = category_a_fact("A1", confirmed=True)
        не_подтверждён = category_a_fact("A1", confirmed=False)
        не_проверяли = category_a_fact("A2", confirmed=None)

        assert подтверждён.value is None
        assert не_подтверждён.value is None
        assert не_проверяли.value is None

        assert подтверждён.raw_value is True
        assert не_подтверждён.raw_value is False
        assert не_проверяли.raw_value is None
        assert не_проверяли.note == NOT_CONNECTED

    def test_ne_podtverzhden_i_ne_proveryali_eto_raznye_sostoyaniya(self) -> None:
        """Пустая колонка «Кат. A» означает «реестр РНУ подключён, факта нет».

        Для A2–A4 та же пустота означает «источник не подключён». Смешать их
        значило бы объявить непроверенные организации чистыми.
        """
        assert category_a_fact("A1", confirmed=False).note != category_a_fact(
            "A2", confirmed=None
        ).note
        assert "не подтверждён" in category_a_fact("A1", confirmed=False).note


# --- Категория A --------------------------------------------------------------


class TestКатегорияA:
    """Жёсткое переопределение уровня сильнее и балла, и нехватки данных."""

    def test_podtverzhdennyy_fakt_delaet_kriticheskim_pri_balle_nol(self) -> None:
        результат = evaluate_organization(значения(категория_a=True))

        assert результат.score == pytest.approx(0.0)
        assert результат.level is RiskLevel.CRITICAL
        assert результат.override_applied.startswith("категория A")

    def test_pereopredelenie_silnee_serogo_urovnya(self) -> None:
        """Полнота 40.9 % отправила бы организацию в серый — но не эту."""
        обычная = evaluate_organization(значения(b5=1.0))
        категорийная = evaluate_organization(значения(b5=1.0, категория_a=True))

        assert обычная.level is RiskLevel.UNKNOWN
        assert обычная.is_preliminary is True
        assert категорийная.level is RiskLevel.CRITICAL
        assert категорийная.is_preliminary is False

    def test_pereopredelenie_rabotaet_dazhe_kogda_ne_izmereno_nichego(self) -> None:
        """Пограничный случай, который ядро само не покрывает.

        При нулевой полноте расчёт завершается досрочно, и жёсткие правила не
        применяются. Для 8.7 это недопустимо: юридически подтверждённый факт
        делает организацию критической и тогда, когда измерить не удалось
        ничего. В наличных данных случай не встречается, но правило методики
        не должно зависеть от того, повезло ли с данными.
        """
        ничего: dict[str, IndicatorValue] = {
            код: unmeasured(код) for код in ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9")
        }
        ничего["A1"] = category_a_fact("A1", confirmed=True)
        for код in ("A2", "A3", "A4"):
            ничего[код] = category_a_fact(код, confirmed=None)

        результат = evaluate_organization(ничего)

        assert результат.score is None
        assert результат.level is RiskLevel.CRITICAL
        assert результат.override_applied.startswith("категория A")

    def test_neproverennyy_fakt_ne_pereopredelyaet(self) -> None:
        """Иначе все 3668 организаций стали бы критическими из-за A2–A4."""
        результат = evaluate_organization(значения(категория_a=None))
        assert результат.override_applied == ""
        assert результат.level is RiskLevel.UNKNOWN

    def test_oproverzhennyy_fakt_ne_pereopredelyaet(self) -> None:
        результат = evaluate_organization(значения(категория_a=False))
        assert результат.override_applied == ""

    def test_prichina_pereopredeleniya_nazyvaet_konkretnyy_priznak(self) -> None:
        результат = evaluate_organization(значения(категория_a=True))
        assert "A1" in результат.override_applied
        assert "реестре недобросовестных" in результат.override_applied

    def test_pravilo_chitaet_fakty_iz_rasshifrovki_a_ne_izvne(self) -> None:
        """Переопределение — часть модели, а не скрытое состояние снаружи."""
        результат = evaluate_organization(значения(категория_a=True))
        решение = category_a_override(результат)
        assert решение is not None
        assert решение[0] is RiskLevel.CRITICAL

    def test_predvaritelnyy_uroven_kategorii_a_tozhe_kriticheskiy(self) -> None:
        """Категория A сильнее балла в обеих колонках уровня."""
        результат = evaluate_organization(значения(категория_a=True))
        assert preliminary_level(результат) is RiskLevel.CRITICAL


# --- Серый остаётся официальным уровнем ---------------------------------------


class TestСерыйОстаётсяОфициальным:
    """Решение заказчика: предварительный балл — не уровень.

    Он показывается рядом с серым, потому что информативен, но в фильтрах и
    агрегатах по уровню объект относится к «нет данных». Тесты этого класса
    обязаны падать при попытке подменить официальный уровень предварительным.
    """

    @staticmethod
    def _критическая_по_баллу() -> RiskResult:
        """Балл 93.3 при полноте 40.9 % — эталонная строка `170640011921`."""
        return evaluate_organization(значения(b3=0.7, b5=1.0, b6=1.0, b8=1.0))

    def test_ball_schitaetsya_i_sokhranyaetsya(self) -> None:
        результат = self._критическая_по_баллу()
        assert результат.score == pytest.approx(93.333, abs=0.001)

    def test_ofitsialnyy_uroven_seryy(self) -> None:
        результат = self._критическая_по_баллу()
        assert результат.level is RiskLevel.UNKNOWN
        assert результат.is_preliminary is True

    def test_predvaritelnyy_uroven_otlichaetsya_ot_ofitsialnogo(self) -> None:
        результат = self._критическая_по_баллу()
        assert preliminary_level(результат) is RiskLevel.CRITICAL
        assert preliminary_level(результат) is not результат.level

    def test_v_agregate_po_urovnyu_eto_net_dannykh(self) -> None:
        """Если бы агрегат брал предварительный уровень, дашборд показал бы
        критическую организацию там, где на деле нечем её оценить."""
        распределение = aggregate_levels([self._критическая_по_баллу()])

        assert распределение[RiskLevel.UNKNOWN] == 1
        assert распределение[RiskLevel.CRITICAL] == 0

    def test_filtr_po_kriticheskomu_urovnyu_ne_nakhodit_takoy_obekt(self) -> None:
        """Прямая проверка требования: фильтр работает по официальному уровню."""
        оценки = [self._критическая_по_баллу(), evaluate_organization(значения(категория_a=True))]

        критические = [о for о in оценки if о.level is RiskLevel.CRITICAL]
        серые = [о for о in оценки if о.level is RiskLevel.UNKNOWN]

        # В критические попала только организация категории A — по юридическому
        # факту, а не по подсказке балла.
        assert len(критические) == 1
        assert критические[0].override_applied.startswith("категория A")
        assert len(серые) == 1

    def test_priznak_predvaritelnosti_est_u_rezultata(self) -> None:
        """Тот самый флаг, по которому фильтры отличают одно от другого."""
        результат = self._критическая_по_баллу()
        assert результат.is_preliminary is True
        assert any("предварительный" in примечание for примечание in результат.notes)

    def test_v_modeli_dannykh_urovnya_dva_a_ne_odin(self) -> None:
        """Свести их в одно поле значит потерять либо честность, либо
        информативность."""
        колонки = set(Organization.__table__.columns.keys())
        assert {"risk_level_preliminary", "risk_level_strict", "risk_is_preliminary"} <= колонки

    def test_territoriya_ne_opredelena_yavnym_znacheniem(self) -> None:
        """У слоя нет ни адреса, ни района, ни КАТО, ни координат.

        «Не определена» — явное состояние, а не вывод из пустого поля.
        """
        assert TerritoryStatus.NOT_DETERMINED.value == "not_determined"
        assert Organization.__table__.c.territory_status.default.arg is (
            TerritoryStatus.NOT_DETERMINED
        )

    def test_u_kategorii_a_ne_ostaetsya_ustarevshego_primechaniya_o_serosti(self) -> None:
        """После жёсткого переопределения примечание о серости обязано исчезнуть.

        Иначе в карточке одновременно стоят «критический» и «уровень серый» —
        два взаимоисключающих утверждения об одном объекте. Сам факт низкой
        полноты при этом не теряется: он виден в `completeness` и в разделе
        «не измерено».
        """
        результат = evaluate_organization(значения(категория_a=True))
        assert результат.level is RiskLevel.CRITICAL
        assert not any("уровень серый" in примечание for примечание in результат.notes)


# --- Golden: сверка с книгой --------------------------------------------------


@pytest.mark.golden
@pytest.mark.slow
class TestОбъёмыКниги:
    def test_3668_organizatsiy(self, выборка: Выборка) -> None:
        assert len(выборка.строки) == EXPECTED_ROW_COUNT == 3668

    def test_dubley_bin_net(self, выборка: Выборка) -> None:
        assert len({строка.bin for строка in выборка.строки}) == 3668
        assert len(bin_index(выборка.строки)) == 3668

    def test_763_bin_poteryali_vedushchie_nuli(self, выборка: Выборка) -> None:
        """Пятая часть выборки. Джойн с 8.5 без `zfill(12)` потерял бы её всю."""
        восстановлено = [с for с in выборка.строки if с.leading_zeros_restored]
        assert len(восстановлено) == 763
        assert len(восстановлено) / len(выборка.строки) == pytest.approx(0.208, abs=0.001)

    def test_vse_bin_dvenadtsatiznachnye(self, выборка: Выборка) -> None:
        assert all(len(строка.bin) == 12 for строка in выборка.строки)
        assert all(строка.bin.isdigit() for строка in выборка.строки)

    def test_izvestnyy_primer_vosstanovleniya(self, выборка: Выборка) -> None:
        указатель = bin_index(выборка.строки)
        строка = указатель["090340012684"]

        assert строка.bin_raw == "90340012684"
        assert строка.leading_zeros_restored is True
        assert "EMS PLUS" in строка.name.upper() or "ЕЭМСИ" in строка.name


@pytest.mark.golden
@pytest.mark.slow
class TestРаспределениеУровней:
    def test_strogoe_raspredelenie_3645_serykh_i_23_kriticheskikh(
        self, выборка: Выборка
    ) -> None:
        """Официальный результат по ТЗ 7.3. Ни одного низкого, среднего, высокого.

        Это не ошибка расчёта, а честное отражение состояния источников:
        максимальная полнота в файле 40.9 % при пороге серого 50 %.
        """
        распределение = aggregate_levels(list(выборка.оценки.values()))
        assert распределение == СТРОГОЕ_РАСПРЕДЕЛЕНИЕ

    def test_predvaritelnoe_raspredelenie(self, выборка: Выборка) -> None:
        """1147 / 2211 / 278 / 32 — то, что подсказывает балл.

        Совпадает с колонкой «Уровень (предв.)» книги, включая то, что
        категория A и здесь сильнее балла: 9 организаций критичны по баллу,
        ещё 23 — по юридическому факту.
        """
        распределение = Counter(
            preliminary_level(оценка).value for оценка in выборка.оценки.values()
        )
        assert распределение == Counter(
            {уровень.value: сколько for уровень, сколько in ПРЕДВАРИТЕЛЬНОЕ_РАСПРЕДЕЛЕНИЕ.items()}
        )

    def test_predvaritelnoe_i_strogoe_rashodyatsya_u_3645_strok(
        self, выборка: Выборка
    ) -> None:
        """Ровно та цена, которую слой платит за 41 % обеспеченности."""
        разошлись = [
            бин
            for бин, оценка in выборка.оценки.items()
            if preliminary_level(оценка) is not оценка.level
        ]
        assert len(разошлись) == 3645

    def test_maksimalnyy_ball_93_3(self, выборка: Выборка) -> None:
        баллы = [о.score for о in выборка.оценки.values() if о.score is not None]
        assert max(баллы) == pytest.approx(93.3, abs=0.05)

    def test_ball_rovno_nol_u_671_organizatsii(self, выборка: Выборка) -> None:
        """Ноль здесь — измеренный ноль: все доступные признаки проверены и
        не сработали. От «не измерено» он отличается наличием балла."""
        нулевые = [о for о in выборка.оценки.values() if о.score == 0.0]
        assert len(нулевые) == 671
        assert all(о.score is not None for о in нулевые)

    @pytest.mark.parametrize(
        ("бин", "ожидаемое"), sorted(ЭТАЛОННЫЕ_ОРГАНИЗАЦИИ.items())
    )
    def test_etalonnye_organizatsii(
        self, выборка: Выборка, бин: str, ожидаемое: tuple[float, RiskLevel]
    ) -> None:
        ожидаемый_балл, ожидаемый_предварительный = ожидаемое
        оценка = выборка.оценки[бин]

        assert оценка.score is not None
        assert round(оценка.score, 1) == pytest.approx(ожидаемый_балл, abs=0.05)
        assert preliminary_level(оценка) is ожидаемый_предварительный
        # Официальный уровень у всех пяти — серый, включая ту, что набрала 93.3.
        assert оценка.level is RiskLevel.UNKNOWN

    def test_etalon_170640011921_schitaetsya_na_soroka_pyati(self, выборка: Выборка) -> None:
        оценка = выборка.оценки["170640011921"]
        assert оценка.raw_score == pytest.approx(42.0)
        assert оценка.available_weight == pytest.approx(45.0)
        assert оценка.completeness == pytest.approx(0.409, abs=0.001)

    def test_etalon_090340012684_schitaetsya_na_tridtsati_pyati(self, выборка: Выборка) -> None:
        """У этой организации нет сведений об ОКЭД — знаменатель 35, не 45."""
        оценка = выборка.оценки["090340012684"]
        assert оценка.raw_score == pytest.approx(31.0)
        assert оценка.available_weight == pytest.approx(35.0)
        assert оценка.completeness == pytest.approx(0.318, abs=0.001)


@pytest.mark.golden
@pytest.mark.slow
class TestПолнота:
    def test_polnota_prinimaet_rovno_dva_znacheniya(self, выборка: Выборка) -> None:
        значения_полноты = {round(о.completeness, 3) for о in выборка.оценки.values()}
        assert значения_полноты == {0.409, 0.318}

    def test_dostupnyy_ves_45_u_2904_i_35_u_764(self, выборка: Выборка) -> None:
        веса = Counter(о.available_weight for о in выборка.оценки.values())
        assert веса == Counter({45.0: 2904, 35.0: 764})

    def test_764_eto_763_bez_okeда_plyus_odna_bez_iin(self, выборка: Выборка) -> None:
        """Тонкость, которую легко потерять при пересказе.

        Docstring поля `oked_sections_count` приписывает все 764 строки
        пустому ОКЭД. На деле их 763, а 764-я — единственная организация без
        ИИН руководителя, у которой не измерен B8. Вес совпал случайно: и B6,
        и B8 весят по 10.
        """
        без_окэд = [с for с in выборка.строки if с.b6_value is None]
        без_иин = [с for с in выборка.строки if с.b8_value is None]

        assert len(без_окэд) == 763
        assert len(без_иин) == 1
        assert len(без_окэд) + len(без_иин) == 764
        assert {с.bin for с in без_окэд} & {с.bin for с in без_иин} == set()

    def test_maksimalnaya_polnota_nizhe_poroga_serogo(self, выборка: Выборка) -> None:
        """Главный вывод слоя, проверенный на данных, а не выведенный из весов."""
        максимум = max(о.completeness for о in выборка.оценки.values())
        assert максимум == pytest.approx(0.409, abs=0.001)
        assert максимум < MIN_COMPLETENESS_8_7

    def test_kazhdaya_organizatsiya_libo_seraya_libo_kategoriya_a(
        self, выборка: Выборка
    ) -> None:
        """Прямое следствие предыдущего теста, выраженное по строкам."""
        по_бин = {с.bin: с for с in выборка.строки}
        нарушители = [
            бин
            for бин, оценка in выборка.оценки.items()
            if оценка.level is not RiskLevel.UNKNOWN and not по_бин[бин].is_category_a
        ]
        assert нарушители == []


@pytest.mark.golden
@pytest.mark.slow
class TestКатегорияAНаДанных:
    def test_23_organizatsii_kategorii_a(self, выборка: Выборка) -> None:
        категорийные = [с for с in выборка.строки if с.is_category_a]
        assert len(категорийные) == 23

    def test_vse_23_kriticheskie(self, выборка: Выборка) -> None:
        категорийные = [с.bin for с in выборка.строки if с.is_category_a]
        assert all(выборка.оценки[бин].level is RiskLevel.CRITICAL for бин in категорийные)
        assert all(выборка.оценки[бин].override_applied for бин in категорийные)

    def test_tri_iz_nikh_s_ballom_nol(self, выборка: Выборка) -> None:
        """Эталон жёсткого переопределения: балл 0, уровень «критический».

        Проверочный пример 3 листа «Формула». Если бы уровень выводился из
        балла, эти три организации оказались бы низкорисковыми.
        """
        нулевые = {
            с.bin
            for с in выборка.строки
            if с.is_category_a and выборка.оценки[с.bin].score == 0.0
        }
        assert нулевые == КАТЕГОРИЯ_A_С_НУЛЁМ
        assert all(выборка.оценки[бин].level is RiskLevel.CRITICAL for бин in нулевые)

    def test_kategoriya_a_edinstvennyy_neseryy_uroven_v_sloe(
        self, выборка: Выборка
    ) -> None:
        несерые = [о for о in выборка.оценки.values() if о.level is not RiskLevel.UNKNOWN]
        assert len(несерые) == 23
        assert all(о.level is RiskLevel.CRITICAL for о in несерые)


@pytest.mark.golden
@pytest.mark.slow
class TestСверкаСВитринойКниги:
    """Построчная сверка нашего расчёта с витриной книги — 3668 строк.

    Книга посчитала балл сама, и наш расчёт обязан его воспроизводить. Ни одна
    строка не расходится: ни по S_raw, ни по W_avail, ни по баллу, ни по обоим
    уровням.
    """

    def test_syroy_ball_i_dostupnyy_ves_sovpadayut(self, выборка: Выборка) -> None:
        расхождения = [
            строка.bin
            for строка in выборка.строки
            if выборка.оценки[строка.bin].raw_score != pytest.approx(строка.book_raw_score)
            or выборка.оценки[строка.bin].available_weight
            != pytest.approx(строка.book_available_weight)
        ]
        assert расхождения == []

    def test_ball_sovpadaet_postrochno(self, выборка: Выборка) -> None:
        расхождения = [
            строка.bin
            for строка in выборка.строки
            if выборка.оценки[строка.bin].score is None
            or abs(выборка.оценки[строка.bin].score - строка.book_score) > 0.05  # type: ignore[operator]
        ]
        assert расхождения == []

    def test_polnota_sovpadaet_postrochno(self, выборка: Выборка) -> None:
        расхождения = [
            строка.bin
            for строка in выборка.строки
            if abs(выборка.оценки[строка.bin].completeness * 100 - строка.book_completeness_percent)
            > 0.05
        ]
        assert расхождения == []

    def test_strogiy_uroven_sovpadaet_postrochno(self, выборка: Выборка) -> None:
        расхождения = [
            строка.bin
            for строка in выборка.строки
            if УРОВНИ_КНИГИ[строка.book_level_strict] is not выборка.оценки[строка.bin].level
        ]
        assert расхождения == []

    def test_predvaritelnyy_uroven_sovpadaet_postrochno(self, выборка: Выборка) -> None:
        расхождения = [
            строка.bin
            for строка in выборка.строки
            if УРОВНИ_КНИГИ[строка.book_level_preliminary]
            is not preliminary_level(выборка.оценки[строка.bin])
        ]
        assert расхождения == []

    def test_v_knige_tolko_dva_strogikh_urovnya(self, выборка: Выборка) -> None:
        уровни = {строка.book_level_strict for строка in выборка.строки}
        assert уровни == {"серый (недостаточно данных)", "критический"}

    def test_neizmerennoe_est_u_kazhdoy_stroki(self, выборка: Выборка) -> None:
        """Раздел «не измерено» непуст у всех 3668 организаций без исключения.

        Восемь индикаторов не подключены ни у кого, поэтому карточка риска
        обязана объяснять серый уровень на каждой странице слоя.
        """
        пустые = [
            строка.bin
            for строка in выборка.строки
            if not НЕПОДКЛЮЧЁННЫЕ_КОДЫ.issubset(
                {ф.code for ф in выборка.оценки[строка.bin].unmeasured_factors}
            )
        ]
        assert пустые == []
