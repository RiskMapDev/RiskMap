"""Тесты слоя 8.4 «Госзакупки».

Расчётный лист книги 8.4 не содержит ни одной формулы — это статический
экспорт результатов, посчитанных вне Excel. Поэтому сверка здесь устроена
жёстче, чем в слое 8.3: мало воспроизвести итог, надо ещё показать, что
значения метрик выводятся из сырых листов. Класс `TestVyvodMetrikIzSyrya`
занимается именно этим и заодно фиксирует два места, где книга сама себе
противоречит.

Главные проверяемые свойства методики:

* «нет данных» никогда не превращается в ноль — недоступная метрика выпадает
  и из числителя, и из знаменателя;
* категория A даёт критический уровень независимо от балла **и независимо от
  полноты** — это установленный юридический факт, а не расчётный признак;
* порог «≥ 75 → критический» на реальных данных не достигается ни разу
  (максимум 67,1), поэтому проверяется на синтетике.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.importers.procurement_8_4 import (
    EXPECTED_CONTRACTS,
    EXPECTED_DISTRICTS,
    EXPECTED_ORGANIZATIONS,
    EXPECTED_SHEETS,
    EXPECTED_SUPPLIERS,
    ProcurementWorkbook,
    clean_bool,
    clean_number,
    clean_text,
    derive_indicators,
    evaluate_contracts,
    excel_serial_to_date,
    load_workbook_8_4,
    normalize_bin,
    parse_legal_address,
    resolve_workbook,
)
from app.risk.core import RiskLevel
from app.risk.layers.procurement import (
    AMOUNT_QUARTILE,
    DEGENERATE_INDICATORS,
    INDICATORS,
    MIN_COMPLETENESS,
    PROCUREMENT_8_4,
    ContractRiskInputs,
    SupplierRiskProfile,
    derive_b1,
    derive_b2,
    derive_b3,
    derive_b4,
    derive_b5,
    derive_b6,
    derive_b7,
    derive_b9,
    evaluate_contract,
)

# --- Контрольные значения книги (docs/audit/02-…, п. 9) ----------------------

BOOK_SCORE_MIN = 11.5
BOOK_SCORE_MAX = 67.1
BOOK_SCORE_SUM = 11_480.90
BOOK_SCORE_AVG = 32.3406
BOOK_TOTAL_AMOUNT = 7_198_964_138.99
BOOK_LEVEL_COUNTS = {
    "низкий": 89,
    "средний": 172,
    "высокий": 43,
    "критический": 48,
    "серый (недостаточно данных)": 3,
}
BOOK_K_DISTRIBUTION = {1.00: 236, 1.15: 107, 1.30: 12}
BOOK_W_AVAIL_DISTRIBUTION = {45: 3, 60: 129, 70: 44, 85: 133, 100: 46}
BOOK_CATEGORY_A_BINS = {
    "170240016026",
    "190740016682",
    "221240004720",
    "230340031364",
}
BOOK_CATEGORY_A_CONTRACTS = 48
BOOK_ONE_SOURCE_CONTRACTS = 107
BOOK_EMAGAZIN_CONTRACTS = 21
BOOK_TERMINATED_CONTRACTS = 43
BOOK_DISTRICT_COUNTS = {
    "Карасайский район": 85,
    "Илийский район": 75,
    "г. Конаев": 43,
    "Талгарский район": 39,
    "Енбекшиказахский район": 35,
    "Жамбылский район": 25,
    "Балхашский район": 23,
    "г. Алатау": 15,
    "г. Алматы": 15,
}

# Договоры с дефектной строкой (см. `TestDefektKnigi`).
DEFECT_CONTRACTS = ("10303009", "10318868", "10408714")


# --- Фикстуры ----------------------------------------------------------------


@pytest.fixture(scope="module")
def workbook_path() -> Path:
    source_dir = get_settings().source_data_dir
    if not source_dir.is_dir():
        pytest.skip(f"Каталог источников недоступен: {source_dir}")
    try:
        return resolve_workbook(source_dir)
    except FileNotFoundError as error:
        pytest.skip(str(error))


@pytest.fixture(scope="module")
def book(workbook_path: Path) -> ProcurementWorkbook:
    return load_workbook_8_4(workbook_path)


# --- Разбор источника --------------------------------------------------------


class TestRazborYacheek:
    """Заглушки, числа-строки и БИН с потерянными нулями."""

    @pytest.mark.parametrize("zaglushka", ["—", "nan", "NaN", "None", "", "  ", "-"])
    def test_zaglushki_eto_otsutstvie_dannykh(self, zaglushka: str) -> None:
        """`'—'` и `'nan'` — строки, а не пустые ячейки, и фильтр по «пусто» их не ловит."""
        assert clean_text(zaglushka) is None

    def test_osmyslennyy_tekst_sokhranyaetsya(self) -> None:
        assert clean_text("Открытый конкурс") == "Открытый конкурс"
        assert clean_text("  Товар  ") == "Товар"

    @pytest.mark.parametrize(
        ("yacheyka", "chislo"),
        [
            ("11 953 000.00", 11_953_000.0),
            ("11\xa0953\xa0000.00", 11_953_000.0),  # неразрывный пробел
            ("8 248 889.60", 8_248_889.60),
            ("5.0", 5.0),
            (188736, 188736.0),
            (67.1, 67.1),
        ],
    )
    def test_chisla_zapisannye_strokami(self, yacheyka: object, chislo: float) -> None:
        assert clean_number(yacheyka) == pytest.approx(chislo)

    @pytest.mark.parametrize("zaglushka", ["nan", "—", "", None])
    def test_zaglushka_ne_stanovitsya_nulyom(self, zaglushka: object) -> None:
        """Ключевое требование методики: «нет данных» ≠ «нет риска»."""
        assert clean_number(zaglushka) is None

    def test_bin_vosstanavlivaet_veduschie_nuli(self) -> None:
        """763 организации из 3 668 записаны с потерянными нулями."""
        assert normalize_bin(440010133) == "000440010133"
        assert normalize_bin("440010133") == "000440010133"
        assert normalize_bin(200940021640) == "200940021640"

    def test_bin_vsegda_dvenadtsat_znakov(self) -> None:
        for raw in (440010133, 12345678901, 200940021640):
            assert len(normalize_bin(raw) or "") == 12

    def test_bulevy_priznaki_zapisany_strokami(self) -> None:
        assert clean_bool("True") is True
        assert clean_bool("False") is False
        assert clean_bool(True) is True

    def test_excel_seriynaya_data(self) -> None:
        """В `contract_additions` даты — числа, а не даты, в отличие от `contract_details`.

        Опорные точки эпохи 1899-12-30 (сдвиг учитывает несуществующее
        29.02.1900, которое Excel считает существующим): серийный номер 61
        соответствует 1900-03-01, номер 45292 — 2024-01-01.
        """
        assert excel_serial_to_date(61) == date(1900, 3, 1)
        assert excel_serial_to_date(45292) == date(2024, 1, 1)
        assert excel_serial_to_date(45415.549363425926) == date(2024, 5, 3)
        assert excel_serial_to_date(45412) == date(2024, 4, 30)
        assert excel_serial_to_date(None) is None
        assert excel_serial_to_date("nan") is None

    def test_razbor_yuridicheskogo_adresa(self) -> None:
        address = parse_legal_address(
            "Страна: Казахстан, Область: Алматинская, Район: Карасайский, "
            "Село: Каскелен, Улица: Наурызбай, Дом: 2"
        )
        assert address.region == "Алматинская"
        assert address.district == "Карасайский"
        assert address.territory_name == "Карасайский"

    def test_adres_bez_rayona_daet_gorod(self) -> None:
        address = parse_legal_address("Страна: Казахстан, Область: Алматинская, Город: Конаев")
        assert address.district is None
        assert address.territory_name == "Конаев"


# --- Модель ------------------------------------------------------------------


class TestModel:
    def test_summa_vesov_ravna_sto(self) -> None:
        assert sum(spec.weight for spec in INDICATORS) == pytest.approx(100.0)

    def test_devyat_ballirumykh_metrik(self) -> None:
        assert len(INDICATORS) == 9
        assert [spec.code for spec in INDICATORS] == [f"B{i}" for i in range(1, 10)]

    def test_porog_polnoty_pyatdesyat_protsentov(self) -> None:
        assert PROCUREMENT_8_4.min_completeness == MIN_COMPLETENESS == 0.5


class TestVyvodMetrik:
    """Пороговые правила B1…B9 из листа «Реестр метрик»."""

    @pytest.mark.parametrize(
        ("sposob", "znachenie"),
        [
            ("Из одного источника путем прямого заключения", 1.0),
            ("Электронный магазин", 0.5),
            ("Открытый конкурс", 0.0),
            ("Запрос ценовых предложений", 0.0),
        ],
    )
    def test_b1_po_sposobu_zakupki(self, sposob: str, znachenie: float) -> None:
        assert derive_b1(sposob) == znachenie

    def test_b1_bez_sposoba_ne_izmeren(self) -> None:
        """Способ неизвестен — метрика недоступна, а не равна нулю."""
        assert derive_b1(None) is None

    @pytest.mark.parametrize(
        ("zayavki", "znachenie"), [(0, 1.0), (1, 1.0), (2, 0.6), (3, 0.3), (4, 0.0), (11, 0.0)]
    )
    def test_b2_po_chislu_zayavok(self, zayavki: float, znachenie: float) -> None:
        assert derive_b2(zayavki) == znachenie

    def test_b2_bez_obyavleniya_ne_izmeren(self) -> None:
        """Нет объявления — нет числа заявок. Это не «конкуренция в норме»."""
        assert derive_b2(None) is None

    @pytest.mark.parametrize(
        ("para", "vsego", "znachenie"),
        [(7, 10, 1.0), (5, 10, 0.6), (4, 10, 0.0), (10, 10, 1.0)],
    )
    def test_b3_po_dole_dogovorov(self, para: int, vsego: int, znachenie: float) -> None:
        assert derive_b3(para, vsego) == znachenie

    def test_b3_ne_schitaetsya_na_dvukh_dogovorakh(self) -> None:
        """Доля 100 % у заказчика с двумя договорами ничего не означает."""
        assert derive_b3(2, 2) is None

    @pytest.mark.parametrize(("n", "znachenie"), [(5, 1.0), (6, 1.0), (3, 0.6), (2, 0.0)])
    def test_b4_po_chislu_zakupok_iz_odnogo_istochnika(self, n: int, znachenie: float) -> None:
        assert derive_b4(n) == znachenie

    @pytest.mark.parametrize(("n", "znachenie"), [(3, 1.0), (2, 0.6), (1, 0.3), (0, 0.0)])
    def test_b5_po_prodleniyam_sroka(self, n: int, znachenie: float) -> None:
        assert derive_b5(n) == znachenie

    @pytest.mark.parametrize(
        ("summy", "znachenie"),
        [
            ([100.0, 150.0], 1.0),
            ([100.0, 125.0], 0.6),
            ([100.0, 106.0], 0.3),
            ([100.0, 101.0], 0.0),
            ([100.0], 0.0),
        ],
    )
    def test_b6_po_rostu_summy(self, summy: list[float], znachenie: float) -> None:
        assert derive_b6(summy) == znachenie

    def test_b6_bez_dopsoglasheniy_ne_izmeren(self) -> None:
        assert derive_b6([]) is None

    def test_b7_po_profilyu_postavshchika(self) -> None:
        assert derive_b7(no_physical_activity=True, n_contracts=100.0) == 1.0
        assert derive_b7(no_physical_activity=False, n_contracts=1.0) == 0.5
        assert derive_b7(no_physical_activity=False, n_contracts=50.0) == 0.0

    def test_b9_po_priznakam_fiktivnosti(self) -> None:
        assert derive_b9(
            nominal_director=True, mass_address=False, high_oked_diversity=False
        ) == 1.0
        assert derive_b9(
            nominal_director=False, mass_address=True, high_oked_diversity=False
        ) == 1.0
        assert derive_b9(
            nominal_director=False, mass_address=False, high_oked_diversity=True
        ) == 0.5
        assert (
            derive_b9(nominal_director=False, mass_address=False, high_oked_diversity=False) == 0.0
        )


# --- Расчёт ------------------------------------------------------------------


def _contract(
    *,
    indicators: dict[str, float | None] | None = None,
    in_rnu_gz: bool = False,
    in_lzhepred_list: bool = False,
    final_amount: float | None = None,
    is_terminated: bool = False,
) -> ContractRiskInputs:
    return ContractRiskInputs(
        contract_id="TEST-1",
        supplier=SupplierRiskProfile(
            bin="000000000001",
            name="ТОО Тест",
            in_rnu_gz=in_rnu_gz,
            in_lzhepred_list=in_lzhepred_list,
        ),
        district="Карасайский район",
        indicators=indicators or {},
        final_amount=final_amount,
        is_terminated=is_terminated,
    )


class TestKoeffitsientZnachimosti:
    def test_bez_priznakov_edinitsa(self) -> None:
        assert _contract().significance_multiplier == 1.00

    def test_summa_vyshe_kvartilya_daet_115(self) -> None:
        assert _contract(final_amount=AMOUNT_QUARTILE).significance_multiplier == 1.15

    def test_rastorzhenie_daet_115(self) -> None:
        assert _contract(is_terminated=True).significance_multiplier == 1.15

    def test_oba_priznaka_dayut_130(self) -> None:
        """Округление обязательно: 1.0 + 0.15 + 0.15 в double даёт 1.2999999999999998."""
        contract = _contract(final_amount=1e9, is_terminated=True)
        assert contract.significance_multiplier == 1.30

    def test_summa_nizhe_kvartilya_ne_schitaetsya(self) -> None:
        assert _contract(final_amount=AMOUNT_QUARTILE - 1).significance_multiplier == 1.00

    def test_neizvestnaya_summa_ne_povyshaet_koeffitsient(self) -> None:
        assert _contract(final_amount=None).significance_multiplier == 1.00


class TestRaschetBalla:
    def test_proverochnyy_primer_iz_knigi(self) -> None:
        """Договор 22529487 с листа «Формула», разобранный по шагам.

        B1 = 1,0 · B7 = 1,0 · B9 = 1,0 · B5 = B6 = B8 = 0 · B2, B3, B4 недоступны.
        W_avail = 15+10+10+10+5+10 = 60; S_raw = 35; S_norm = 58,3; K = 1,15;
        Risk Score = 67,1; полнота 60 % ≥ 50 % → уровень высокий.
        """
        result = evaluate_contract(
            _contract(
                indicators={
                    "B1": 1.0, "B2": None, "B3": None, "B4": None, "B5": 0.0,
                    "B6": 0.0, "B7": 1.0, "B8": 0.0, "B9": 1.0,
                },
                is_terminated=True,
            )
        )
        assert result.raw_score == pytest.approx(35.0)
        assert result.available_weight == pytest.approx(60.0)
        assert result.normalized_score == pytest.approx(58.333, abs=0.001)
        assert result.significance_multiplier == 1.15
        assert result.score == pytest.approx(67.1, abs=0.05)
        assert result.level is RiskLevel.HIGH

    def test_nedostupnaya_metrika_ne_popadaet_v_znamenatel(self) -> None:
        """Подстановка нуля запрещена методикой явно."""
        s_propuskom = evaluate_contract(_contract(indicators={"B1": 1.0, "B2": None}))
        s_nulyom = evaluate_contract(_contract(indicators={"B1": 1.0, "B2": 0.0}))

        assert s_propuskom.available_weight == pytest.approx(15.0)
        assert s_propuskom.normalized_score == pytest.approx(100.0)
        assert s_nulyom.available_weight == pytest.approx(30.0)
        assert s_nulyom.normalized_score == pytest.approx(50.0)

    def test_ball_ne_prevyshaet_sto(self) -> None:
        result = evaluate_contract(
            _contract(
                indicators=dict.fromkeys((spec.code for spec in INDICATORS), 1.0),
                final_amount=1e9,
                is_terminated=True,
            )
        )
        assert result.score == pytest.approx(100.0)

    def test_porog_75_dostizhim_na_sintetike(self) -> None:
        """На данных книги максимум 67,1, но ветка порога существует и работает."""
        result = evaluate_contract(
            _contract(indicators=dict.fromkeys((spec.code for spec in INDICATORS), 0.8))
        )
        assert result.score == pytest.approx(80.0)
        assert result.level is RiskLevel.CRITICAL
        assert not result.is_category_a


class TestSeryyUroven:
    def test_polnota_nizhe_50_daet_seryy(self) -> None:
        result = evaluate_contract(_contract(indicators={"B1": 0.0, "B5": 0.0, "B7": 1.0}))
        assert result.risk.completeness == pytest.approx(0.35)
        assert result.level is RiskLevel.UNKNOWN
        assert result.level_label_ru == "серый (недостаточно данных)"
        assert result.risk.is_preliminary

    def test_predvaritelnyy_ball_ostayotsya_vidnym(self) -> None:
        """Серый уровень не прячет балл: он информативен, но не основание."""
        result = evaluate_contract(_contract(indicators={"B1": 1.0, "B5": 0.0}))
        assert result.level is RiskLevel.UNKNOWN
        assert result.score is not None

    def test_polnota_rovno_50_uroven_schitaetsya(self) -> None:
        result = evaluate_contract(
            _contract(indicators={"B1": 0.0, "B2": 0.0, "B3": 0.0, "B5": 0.0, "B7": 0.0})
        )
        assert result.risk.completeness == pytest.approx(0.65)
        assert result.level is RiskLevel.LOW


class TestKategoriyaA:
    def test_rnu_delaet_kriticheskim_pri_lyubom_balle(self) -> None:
        result = evaluate_contract(
            _contract(indicators=dict.fromkeys((s.code for s in INDICATORS), 0.0), in_rnu_gz=True)
        )
        assert result.score == pytest.approx(0.0)
        assert result.level is RiskLevel.CRITICAL
        assert result.is_category_a
        assert "недобросовестных" in result.risk.override_applied

    def test_lzhepredpriyatie_delaet_kriticheskim(self) -> None:
        result = evaluate_contract(
            _contract(
                indicators=dict.fromkeys((s.code for s in INDICATORS), 0.0),
                in_lzhepred_list=True,
            )
        )
        assert result.level is RiskLevel.CRITICAL
        assert "лжепредприятий" in result.risk.override_applied

    def test_kategoriya_a_silnee_serogo_urovnya(self) -> None:
        """Порядок проверок критичен: категория A имеет приоритет над серым.

        Нехватка данных не должна спасать поставщика из реестра от уровня.
        """
        result = evaluate_contract(_contract(indicators={"B1": 0.0}, in_rnu_gz=True))
        assert result.risk.completeness == pytest.approx(0.15)
        assert result.level is RiskLevel.CRITICAL
        assert not result.risk.is_preliminary

    def test_bez_kategorii_a_pereopredeleniya_net(self) -> None:
        result = evaluate_contract(_contract(indicators={"B1": 0.0}))
        assert result.risk.override_applied == ""


# --- Сверка с книгой ---------------------------------------------------------


@pytest.mark.golden
class TestSverkaSKnigoy:
    def test_sostav_knigi(self, book: ProcurementWorkbook) -> None:
        assert len(book.sheet_names) == EXPECTED_SHEETS
        assert len(book.calc_rows) == EXPECTED_CONTRACTS
        assert len(book.contracts) == EXPECTED_CONTRACTS
        assert len(book.organizations) == EXPECTED_ORGANIZATIONS

    def test_26_postavshchikov_9_rayonov_odna_oblast(self, book: ProcurementWorkbook) -> None:
        assert len({row.supplier_bin for row in book.calc_rows}) == EXPECTED_SUPPLIERS
        assert len({row.district for row in book.calc_rows}) == EXPECTED_DISTRICTS
        assert {row.region for row in book.calc_rows} == {"Алматинская область"}

    def test_raspredelenie_po_rayonam(self, book: ProcurementWorkbook) -> None:
        counts = Counter(row.district for row in book.calc_rows)
        assert dict(counts) == BOOK_DISTRICT_COUNTS

    def test_vse_355_dogovorov_vosproizvodyatsya(self, book: ProcurementWorkbook) -> None:
        """Главная сверка: S_raw, W_avail, S_norm, K, Risk Score и уровень."""
        for calc, result in zip(book.calc_rows, evaluate_contracts(book), strict=True):
            assert result.contract_id == calc.contract_id
            assert result.raw_score == pytest.approx(calc.s_raw, abs=0.01), calc.contract_id
            assert result.available_weight == pytest.approx(calc.w_avail), calc.contract_id
            assert result.normalized_score == pytest.approx(calc.s_norm, abs=0.05), calc.contract_id
            assert result.significance_multiplier == pytest.approx(calc.k), calc.contract_id
            assert result.score == pytest.approx(calc.risk_score, abs=0.05), calc.contract_id
            assert result.level_label_ru == calc.level, calc.contract_id

    def test_agregaty_ballov(self, book: ProcurementWorkbook) -> None:
        scores = [round(r.score or 0.0, 1) for r in evaluate_contracts(book)]
        assert min(scores) == pytest.approx(BOOK_SCORE_MIN)
        assert max(scores) == pytest.approx(BOOK_SCORE_MAX)
        assert sum(scores) == pytest.approx(BOOK_SCORE_SUM, abs=0.05)
        assert sum(scores) / len(scores) == pytest.approx(BOOK_SCORE_AVG, abs=0.001)

    def test_raspredelenie_urovney(self, book: ProcurementWorkbook) -> None:
        counts = Counter(r.level_label_ru for r in evaluate_contracts(book))
        assert dict(counts) == BOOK_LEVEL_COUNTS

    def test_raspredelenie_koeffitsienta_k(self, book: ProcurementWorkbook) -> None:
        counts = Counter(r.significance_multiplier for r in evaluate_contracts(book))
        assert dict(counts) == BOOK_K_DISTRIBUTION

    def test_raspredelenie_dostupnogo_vesa(self, book: ProcurementWorkbook) -> None:
        counts = Counter(int(r.available_weight) for r in evaluate_contracts(book))
        assert dict(counts) == BOOK_W_AVAIL_DISTRIBUTION

    def test_summa_dogovorov(self, book: ProcurementWorkbook) -> None:
        total = sum(row.final_amount or 0.0 for row in book.calc_rows)
        assert total == pytest.approx(BOOK_TOTAL_AMOUNT, abs=0.01)

    def test_kategoriya_a_chetyre_postavshchika_48_dogovorov(
        self, book: ProcurementWorkbook
    ) -> None:
        results = evaluate_contracts(book)
        category_a = [r for r in results if r.is_category_a]
        assert {r.supplier_bin for r in category_a} == BOOK_CATEGORY_A_BINS
        assert len(category_a) == BOOK_CATEGORY_A_CONTRACTS

    def test_vse_kriticheskie_polucheny_cherez_kategoriyu_a(
        self, book: ProcurementWorkbook
    ) -> None:
        """Порог «≥ 75» не срабатывает ни разу: максимум по выборке 67,1.

        Это свойство данных, а не отсутствие критических договоров. Если
        когда-нибудь появится договор с баллом выше 75, он станет критическим
        по порогу — ветка проверена на синтетике отдельно.
        """
        critical = [r for r in evaluate_contracts(book) if r.level is RiskLevel.CRITICAL]
        assert len(critical) == BOOK_CATEGORY_A_CONTRACTS
        assert all(r.is_category_a for r in critical)
        assert max(r.score or 0.0 for r in critical) < 75.0

    def test_rastorgnutykh_43(self, book: ProcurementWorkbook) -> None:
        assert sum(c.is_terminated for c in book.contracts.values()) == BOOK_TERMINATED_CONTRACTS

    def test_zakupok_iz_odnogo_istochnika_107(self, book: ProcurementWorkbook) -> None:
        values = [derive_b1(row.method) for row in book.calc_rows]
        assert sum(v == 1.0 for v in values) == BOOK_ONE_SOURCE_CONTRACTS
        assert sum(v == 0.5 for v in values) == BOOK_EMAGAZIN_CONTRACTS

    @pytest.mark.parametrize(
        ("dogovor", "s_norm", "k", "ball", "uroven"),
        [
            ("22333284", 58.3, 1.15, 67.1, "высокий"),
            ("14863203", 50.0, 1.00, 50.0, "критический"),
            ("23028315", 35.3, 1.30, 45.9, "критический"),
        ],
    )
    def test_etalonnye_dogovory(
        self,
        book: ProcurementWorkbook,
        dogovor: str,
        s_norm: float,
        k: float,
        ball: float,
        uroven: str,
    ) -> None:
        result = next(r for r in evaluate_contracts(book) if r.contract_id == dogovor)
        assert result.normalized_score == pytest.approx(s_norm, abs=0.05)
        assert result.significance_multiplier == pytest.approx(k)
        assert result.score == pytest.approx(ball, abs=0.05)
        assert result.level_label_ru == uroven

    def test_b4_vyrozhden(self, book: ProcurementWorkbook) -> None:
        """Все 224 измеренных значения B4 равны нулю — 10 % веса не работает."""
        measured = [
            row.indicators["B4"] for row in book.calc_rows if row.indicators["B4"] is not None
        ]
        assert len(measured) == 224
        assert set(measured) == {0.0}
        assert {"B4"} == DEGENERATE_INDICATORS

    def test_geoprivyazka_pokryvaet_vse_dogovory(self, book: ProcurementWorkbook) -> None:
        """Юр. адрес поставщика даёт 355 из 355 — ради этого и выбран."""
        for row in book.calc_rows:
            address = book.addresses.get(row.supplier_bin)
            assert address is not None, row.supplier_bin
            assert address.territory_name is not None, row.supplier_bin


# --- Вывод метрик из сырья и дефекты книги -----------------------------------


@pytest.mark.golden
class TestVyvodMetrikIzSyrya:
    """Независимый пересчёт B1…B9 из сырых листов против значений книги.

    Расчётный лист формул не содержит, поэтому без этой проверки утверждать,
    что методика воспроизводится, было бы нечем.
    """

    def test_metriki_vyvodyatsya_iz_syrykh_listov(self, book: ProcurementWorkbook) -> None:
        derived = derive_indicators(book)
        agreement: dict[str, int] = {}
        for row in book.calc_rows:
            for code, value in derived[row.contract_id].items():
                if code == "B8":
                    continue  # справочник ОКЭД в книгу не вложен
                expected = row.indicators[code]
                same = (value is None and expected is None) or (
                    value is not None and expected is not None and abs(value - expected) < 1e-9
                )
                agreement[code] = agreement.get(code, 0) + same

        # B2…B5, B7, B9 воспроизводятся полностью. B1 и B6 — нет, и оба
        # расхождения разобраны отдельными тестами ниже.
        assert agreement["B2"] == EXPECTED_CONTRACTS
        assert agreement["B3"] == EXPECTED_CONTRACTS
        assert agreement["B4"] == EXPECTED_CONTRACTS
        assert agreement["B5"] == EXPECTED_CONTRACTS
        assert agreement["B7"] == EXPECTED_CONTRACTS
        assert agreement["B9"] == EXPECTED_CONTRACTS
        assert agreement["B1"] == EXPECTED_CONTRACTS - len(DEFECT_CONTRACTS)
        assert agreement["B6"] == EXPECTED_CONTRACTS - 8

    def test_b8_ne_vyvoditsya_bez_spravochnika_oked(self, book: ProcurementWorkbook) -> None:
        """`oked.csv` (78 375 строк) в книгу не вложен — B8 только импортируется.

        Заполнить его нулём было бы ровно той подстановкой «нет данных = нет
        риска», которую методика запрещает, поэтому вывод возвращает `None`.
        """
        assert "oked" not in {name.casefold() for name in book.sheet_names}
        derived = derive_indicators(book)
        assert all(values["B8"] is None for values in derived.values())

    def test_imya_zakazchika_v_raschetnom_liste_obrezano(
        self, book: ProcurementWorkbook
    ) -> None:
        """Из-за обрезки до 60 знаков разные заказчики схлопываются в одного.

        Поэтому группировки B3 и B4 считаются по полному имени из листа
        `lots`, а не по колонке расчётного листа.
        """
        truncated = {row.customer_truncated for row in book.calc_rows if row.customer_truncated}
        full = {
            book.customer_of(row.contract_id)
            for row in book.calc_rows
            if book.customer_of(row.contract_id)
        }
        assert max(len(name) for name in truncated) <= 60
        assert max(len(name or "") for name in full) > 60


@pytest.mark.golden
class TestDefektKnigi:
    """Два подтверждённых дефекта книги 8.4, зафиксированных явно.

    Оба найдены пересчётом и оба оставлены как расхождение, а не подогнаны.
    """

    def test_defekt_1_b1_zapisan_nulyom_pri_neizvestnom_sposobe(
        self, book: ProcurementWorkbook
    ) -> None:
        """Три договора: в ячейке B1 стоит `0`, но `W_avail` посчитан без B1.

        Разбор. У договоров 10303009, 10318868 и 10408714 способ закупки
        записан строкой-заглушкой `'nan'`, то есть **неизвестен**. В расчётном
        листе книги при этом одновременно:

          * в ячейку `B1` записан `0` — как будто метрика измерена;
          * в `W_avail` записано 45 вместо 60 — как будто метрика недоступна.

        Внутри одной строки это противоречие: метрика не может быть измерена в
        числителе и не измерена в знаменателе.

        Как разрешено. Способ закупки неизвестен → B1 не измерена → не входит
        ни в числитель, ни в знаменатель. Это прямое следствие центрального
        принципа методики («нет данных» ≠ «нет риска») и ядра расчёта.

        Что из этого следует — и здесь вывод расходится с формулировкой
        аудита в `docs/audit/02-…`, п. 10.1. Аудит предполагал, что корректная
        обработка даст `W_avail = 60` и уровень «низкий». На деле корректная
        обработка даёт `W_avail = 45`, полноту 45 % < 50 % и уровень
        **«серый»** — то есть ровно те значения, которые в книге и записаны.
        Дефектна только сама ячейка `B1`: генератор вывел в неё `0` вместо
        пустоты. Все производные величины книги (`W_avail`, `S_norm`,
        `Risk Score`, уровень) верны.

        Практический итог: расхождение с книгой существует и равно ровно трём
        ячейкам `B1`; на баллы и уровни оно не влияет.
        """
        derived = derive_indicators(book)
        for contract_id in DEFECT_CONTRACTS:
            calc = next(row for row in book.calc_rows if row.contract_id == contract_id)

            # Способ закупки — заглушка, то есть сведений нет.
            assert calc.method is None

            # Книга записала в ячейку ноль…
            assert calc.indicators["B1"] == 0.0
            # …но её же W_avail посчитан так, как будто метрика недоступна.
            assert calc.w_avail == 45

            # Наш вывод: метрика не измерена. Это согласуется с W_avail книги
            # и расходится только с содержимым ячейки.
            assert derived[contract_id]["B1"] is None

        # Итоговые величины при этом совпадают с книгой полностью.
        results = {r.contract_id: r for r in evaluate_contracts(book)}
        for contract_id in DEFECT_CONTRACTS:
            calc = next(row for row in book.calc_rows if row.contract_id == contract_id)
            result = results[contract_id]
            assert result.available_weight == 45.0
            assert result.raw_score == pytest.approx(10.0)
            assert result.normalized_score == pytest.approx(22.2, abs=0.05)
            assert result.score == pytest.approx(calc.risk_score, abs=0.05)
            assert result.level is RiskLevel.UNKNOWN
            assert result.risk.completeness == pytest.approx(0.45)

    def test_defekt_2_b6_schitan_v_obratnom_poryadke_versiy(
        self, book: ProcurementWorkbook
    ) -> None:
        """Восемь договоров: рост цены посчитан от последней версии к первой.

        Методика (`Реестр метрик`, B6) требует `growth = last / first`, где
        first и last — первая и последняя версии суммы договора. Для восьми
        договоров книга получила значение, соответствующее обратному
        отношению `first / last`.

        Пример: у договора 19007545 два доп. соглашения — 409 999,99 от
        2023-11-13 и 329 431,00 от 2024-01-06. По методике рост равен
        329 431 / 409 999,99 = 0,80, то есть B6 = 0. В книге записано 0,6,
        что соответствует 409 999,99 / 329 431 = 1,24 — сумма падала, а
        засчитана как выросшая.

        Расхождение оставлено как есть: код считает по методике, книга —
        нет. На восьми договорах из 355 это меняет B6, но ни один из них не
        меняет итоговый уровень (проверяется ниже), поэтому контрольные
        распределения книги сходятся.
        """
        derived = derive_indicators(book)
        disagreeing = [
            row.contract_id
            for row in book.calc_rows
            if not _same(derived[row.contract_id]["B6"], row.indicators["B6"])
        ]
        assert len(disagreeing) == 8

        # Ни одно из расхождений не переводит договор в другой уровень:
        # итоговые уровни книги воспроизводятся полностью (см. соседний тест).
        levels = Counter(r.level_label_ru for r in evaluate_contracts(book))
        assert dict(levels) == BOOK_LEVEL_COUNTS


def _same(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) < 1e-9
