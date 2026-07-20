"""Тесты ядра расчёта риска.

Главное, что здесь проверяется, — что отсутствие данных нигде не превращается
в ноль и не выдаёт себя за благополучие.
"""

from __future__ import annotations

import pytest

from app.risk.core import (
    IndicatorDirection,
    IndicatorSpec,
    IndicatorValue,
    ModelRegistry,
    RiskLevel,
    RiskModelSpec,
    aggregate_levels,
    evaluate,
)

THRESHOLDS = (
    (0.0, RiskLevel.LOW),
    (25.0, RiskLevel.MEDIUM),
    (50.0, RiskLevel.HIGH),
    (75.0, RiskLevel.CRITICAL),
)


def make_spec(**overrides: object) -> RiskModelSpec:
    defaults: dict[str, object] = {
        "code": "test",
        "version": "1.0",
        "title": "Тестовая модель",
        "indicators": (
            IndicatorSpec(code="A", name="Первый", weight=60.0),
            IndicatorSpec(code="B", name="Второй", weight=40.0),
        ),
        "thresholds": THRESHOLDS,
    }
    defaults.update(overrides)
    return RiskModelSpec(**defaults)  # type: ignore[arg-type]


def measured(code: str, value: float) -> IndicatorValue:
    return IndicatorValue(code=code, value=value)


def absent(code: str, note: str = "") -> IndicatorValue:
    return IndicatorValue(code=code, value=None, note=note)


class TestOtsutstvieDannykhNeNol:
    """Центральное требование: «не измерено» ≠ 0."""

    def test_neizmerennyy_indikator_ne_snizhaet_ball(self) -> None:
        spec = make_spec()

        oba = evaluate(spec, {"A": measured("A", 1.0), "B": measured("B", 1.0)})
        tolko_a = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B")})

        # Если бы B считался нулём, балл упал бы до 60. Он остаётся 100.
        assert oba.score == pytest.approx(100.0)
        assert tolko_a.score == pytest.approx(100.0)

    def test_nol_i_otsutstvie_razlichayutsya(self) -> None:
        spec = make_spec()

        s_nulyom = evaluate(spec, {"A": measured("A", 1.0), "B": measured("B", 0.0)})
        bez_znacheniya = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B")})

        assert s_nulyom.score == pytest.approx(60.0)
        assert bez_znacheniya.score == pytest.approx(100.0)
        assert s_nulyom.completeness == pytest.approx(1.0)
        assert bez_znacheniya.completeness == pytest.approx(0.6)

    def test_nichego_ne_izmereno_daet_none_a_ne_nol(self) -> None:
        spec = make_spec()
        result = evaluate(spec, {"A": absent("A"), "B": absent("B")})

        assert result.score is None
        assert result.raw_score is None
        assert result.level is RiskLevel.UNKNOWN
        assert result.completeness == 0.0
        assert "не измерен ни один индикатор" in result.notes

    def test_pustoy_slovar_znacheniy_ravnosilen_otsutstviyu(self) -> None:
        result = evaluate(make_spec(), {})
        assert result.score is None
        assert result.level is RiskLevel.UNKNOWN


class TestNormirovka:
    def test_ball_privoditsya_k_dostupnomu_vesu(self) -> None:
        spec = make_spec()
        result = evaluate(spec, {"A": measured("A", 0.5), "B": absent("B")})

        assert result.raw_score == pytest.approx(30.0)
        assert result.available_weight == pytest.approx(60.0)
        assert result.normalized_score == pytest.approx(50.0)

    def test_polnota_schitaetsya_ot_polnogo_vesa_modeli(self) -> None:
        """Знаменатель полноты — весь вес методики, включая неподключённое.

        Иначе модель с одним работающим индикатором отрапортует 100 %.
        """
        spec = make_spec(
            indicators=(
                IndicatorSpec(code="A", name="Работает", weight=10.0),
                IndicatorSpec(code="B", name="Нет источника", weight=90.0, available=False),
            )
        )
        result = evaluate(spec, {"A": measured("A", 1.0)})

        assert result.completeness == pytest.approx(0.1)
        assert result.total_weight == pytest.approx(100.0)
        assert result.available_weight == pytest.approx(10.0)

    def test_nepodklyuchennyy_indikator_viden_kak_ne_izmereno(self) -> None:
        spec = make_spec(
            indicators=(
                IndicatorSpec(code="A", name="Работает", weight=50.0),
                IndicatorSpec(
                    code="B", name="Нет источника", weight=50.0, available=False, source="КГД"
                ),
            )
        )
        result = evaluate(spec, {"A": measured("A", 1.0)})

        неизмеренные = result.unmeasured_factors
        assert len(неизмеренные) == 1
        assert неизмеренные[0].code == "B"
        assert неизмеренные[0].note == "источник не подключён"
        assert неизмеренные[0].effect == "не измерено"

    def test_znachenie_vne_diapazona_otvergaetsya(self) -> None:
        spec = make_spec()
        with pytest.raises(ValueError, match="вне диапазона"):
            evaluate(spec, {"A": measured("A", 1.5)})

    def test_neizvestnyy_kod_indikatora_otvergaetsya(self) -> None:
        spec = make_spec()
        with pytest.raises(KeyError, match="неизвестных индикаторов"):
            evaluate(spec, {"Z": measured("Z", 1.0)})


class TestUrovni:
    @pytest.mark.parametrize(
        ("ball", "ozhidaemyy"),
        [
            (0.0, RiskLevel.LOW),
            (24.9, RiskLevel.LOW),
            (25.0, RiskLevel.MEDIUM),
            (49.9, RiskLevel.MEDIUM),
            (50.0, RiskLevel.HIGH),
            (74.9, RiskLevel.HIGH),
            (75.0, RiskLevel.CRITICAL),
            (100.0, RiskLevel.CRITICAL),
        ],
    )
    def test_granitsy_porogov_vklyuchayushchie(self, ball: float, ozhidaemyy: RiskLevel) -> None:
        assert make_spec().level_for(ball) is ozhidaemyy

    def test_porogi_dolzhny_vozrastat(self) -> None:
        with pytest.raises(ValueError, match="по возрастанию"):
            make_spec(
                thresholds=(
                    (50.0, RiskLevel.HIGH),
                    (25.0, RiskLevel.MEDIUM),
                )
            )

    def test_net_dannykh_ne_schitaetsya_nizkim_pri_sortirovke(self) -> None:
        """Объект без данных не должен уезжать в «благополучный» конец списка."""
        assert RiskLevel.UNKNOWN.order < RiskLevel.LOW.order
        assert not RiskLevel.UNKNOWN.is_measured


class TestPolnotaISeryyUroven:
    def test_nizkaya_polnota_daet_seryy_uroven(self) -> None:
        spec = make_spec(min_completeness=0.5)
        result = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B")})

        # Балл 100 сам по себе критический, но полнота 60 %… проверим порог ниже.
        assert result.completeness == pytest.approx(0.6)
        assert result.level is RiskLevel.CRITICAL

    def test_polnota_nizhe_poroga_prevrashchaet_uroven_v_seryy(self) -> None:
        spec = make_spec(min_completeness=0.8)
        result = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B")})

        assert result.completeness == pytest.approx(0.6)
        assert result.level is RiskLevel.UNKNOWN
        assert result.is_preliminary is True

    def test_predvaritelnyy_ball_sokhranyaetsya_ryadom_s_serym(self) -> None:
        """Балл виден пользователю, но уровень остаётся серым.

        Так решено для слоя 8.7: прятать посчитанное значение бессмысленно,
        выдавать его за основание — нельзя.
        """
        spec = make_spec(min_completeness=0.8)
        result = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B")})

        assert result.level is RiskLevel.UNKNOWN
        assert result.score == pytest.approx(100.0)
        assert result.is_preliminary is True
        assert any("предварительный" in note for note in result.notes)

    def test_bez_poroga_polnoty_seryy_ne_naznachaetsya(self) -> None:
        """В методике слоя 8.5 серого уровня нет вовсе."""
        spec = make_spec(min_completeness=None)
        result = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B")})

        assert result.level is RiskLevel.CRITICAL
        assert result.is_preliminary is False


class TestKoeffitsientZnachimosti:
    def test_mnozhitel_primenyaetsya_posle_normirovki(self) -> None:
        spec = make_spec(score_multiplier=lambda _: 1.15)
        result = evaluate(spec, {"A": measured("A", 0.5), "B": measured("B", 0.5)})

        assert result.normalized_score == pytest.approx(50.0)
        assert result.score == pytest.approx(57.5)
        assert any("K = 1.15" in note for note in result.notes)

    def test_ball_ne_prevyshaet_shkalu(self) -> None:
        spec = make_spec(score_multiplier=lambda _: 1.30)
        result = evaluate(spec, {"A": measured("A", 1.0), "B": measured("B", 1.0)})

        assert result.score == pytest.approx(100.0)

    def test_mnozhitel_edinitsa_ne_dobavlyaet_zametku(self) -> None:
        spec = make_spec(score_multiplier=lambda _: 1.0)
        result = evaluate(spec, {"A": measured("A", 0.5), "B": measured("B", 0.5)})

        assert not any("K =" in note for note in result.notes)


class TestPolBalla:
    def test_pol_podnimaet_ball(self) -> None:
        """Слой 8.3 реализует переопределение как пол в 75 баллов."""
        spec = make_spec(score_floor=lambda _: 75.0)
        result = evaluate(spec, {"A": measured("A", 0.1), "B": measured("B", 0.1)})

        assert result.score == pytest.approx(75.0)
        assert result.level is RiskLevel.CRITICAL
        assert any("поднят до 75" in note for note in result.notes)

    def test_pol_ne_snizhaet_ball(self) -> None:
        spec = make_spec(score_floor=lambda _: 75.0)
        result = evaluate(spec, {"A": measured("A", 1.0), "B": measured("B", 1.0)})

        assert result.score == pytest.approx(100.0)


class TestZhestkoePereopredelenie:
    def test_kategoriya_a_delaet_kriticheskim(self) -> None:
        spec = make_spec(
            override=lambda _: (RiskLevel.CRITICAL, "категория A: лжепредприятие"),
        )
        result = evaluate(spec, {"A": measured("A", 0.0), "B": measured("B", 0.0)})

        assert result.score == pytest.approx(0.0)
        assert result.level is RiskLevel.CRITICAL
        assert result.override_applied == "категория A: лжепредприятие"

    def test_pereopredelenie_silnee_serogo_urovnya(self) -> None:
        """Нехватка данных не должна спасать объект от жёсткого правила."""
        spec = make_spec(
            min_completeness=0.9,
            override=lambda _: (RiskLevel.CRITICAL, "категория A"),
        )
        result = evaluate(spec, {"A": measured("A", 0.1), "B": absent("B")})

        assert result.completeness == pytest.approx(0.6)
        assert result.level is RiskLevel.CRITICAL
        assert result.is_preliminary is False

    def test_pereopredelenie_ne_srabatyvaet_bez_povoda(self) -> None:
        spec = make_spec(override=lambda _: None)
        result = evaluate(spec, {"A": measured("A", 0.1), "B": measured("B", 0.1)})

        assert result.level is RiskLevel.LOW
        assert result.override_applied == ""


class TestRasshifrovka:
    def test_faktory_soderzhat_vklad_kazhdogo_indikatora(self) -> None:
        spec = make_spec()
        result = evaluate(spec, {"A": measured("A", 0.5), "B": measured("B", 1.0)})

        по_kodu = {f.code: f for f in result.factors}
        assert по_kodu["A"].contribution == pytest.approx(30.0)
        assert по_kodu["B"].contribution == pytest.approx(40.0)
        assert по_kodu["A"].effect == "повысил риск"

    def test_nulevoy_vklad_otmechaetsya_kak_ne_povliyal(self) -> None:
        spec = make_spec()
        result = evaluate(spec, {"A": measured("A", 0.0), "B": measured("B", 1.0)})

        по_kodu = {f.code: f for f in result.factors}
        assert по_kodu["A"].effect == "не повлиял"

    def test_glavnye_faktory_sortiruyutsya_po_vkladu(self) -> None:
        spec = make_spec(
            indicators=(
                IndicatorSpec(code="A", name="Первый", weight=10.0),
                IndicatorSpec(code="B", name="Второй", weight=50.0),
                IndicatorSpec(code="C", name="Третий", weight=40.0),
            )
        )
        result = evaluate(
            spec,
            {
                "A": measured("A", 1.0),
                "B": measured("B", 1.0),
                "C": measured("C", 0.5),
            },
        )

        assert [f.code for f in result.top_factors(2)] == ["B", "C"]

    def test_prichina_otsutstviya_dokhodit_do_polzovatelya(self) -> None:
        spec = make_spec()
        result = evaluate(spec, {"A": measured("A", 1.0), "B": absent("B", "нет данных ОКЭД")})

        неизмеренный = next(f for f in result.factors if f.code == "B")
        assert неизмеренный.note == "нет данных ОКЭД"


class TestSpetsifikatsiyaModeli:
    def test_povtoryayushchiesya_kody_otvergayutsya(self) -> None:
        with pytest.raises(ValueError, match="повторяющиеся коды"):
            make_spec(
                indicators=(
                    IndicatorSpec(code="A", name="Первый", weight=50.0),
                    IndicatorSpec(code="A", name="Дубль", weight=50.0),
                )
            )

    def test_model_bez_indikatorov_otvergaetsya(self) -> None:
        with pytest.raises(ValueError, match="нет ни одного индикатора"):
            make_spec(indicators=())

    def test_zapros_neopisannogo_indikatora(self) -> None:
        with pytest.raises(KeyError, match="не описан"):
            make_spec().indicator("Z")

    def test_napravlenie_indikatora_dokhodit_do_rasshifrovki(self) -> None:
        spec = make_spec(
            indicators=(
                IndicatorSpec(
                    code="A",
                    name="Освоение",
                    weight=100.0,
                    direction=IndicatorDirection.LOWER_IS_RISKIER,
                ),
            )
        )
        result = evaluate(spec, {"A": measured("A", 1.0)})
        assert result.factors[0].direction is IndicatorDirection.LOWER_IS_RISKIER


class TestAgregaty:
    def test_seryy_uroven_popadaet_v_raspredelenie(self) -> None:
        """Серые объекты нельзя прятать из сводки — картина станет радужнее."""
        spec = make_spec()
        results = [
            evaluate(spec, {"A": measured("A", 0.0), "B": measured("B", 0.0)}),
            evaluate(spec, {"A": absent("A"), "B": absent("B")}),
            evaluate(spec, {"A": absent("A"), "B": absent("B")}),
        ]

        counts = aggregate_levels(results)
        assert counts[RiskLevel.LOW] == 1
        assert counts[RiskLevel.UNKNOWN] == 2
        assert sum(counts.values()) == 3

    def test_vse_urovni_prisutstvuyut_v_klyuchakh(self) -> None:
        counts = aggregate_levels([])
        assert set(counts) == set(RiskLevel)
        assert all(v == 0 for v in counts.values())


class TestReestrModeley:
    def test_versii_ne_perezapisyvayutsya(self) -> None:
        registry = ModelRegistry()
        registry.register(make_spec(version="1.0"))
        with pytest.raises(ValueError, match="уже зарегистрирована"):
            registry.register(make_spec(version="1.0"))

    def test_staraya_versiya_ostayotsya_dostupnoy(self) -> None:
        """Правка весов не должна переписывать историю оценок."""
        registry = ModelRegistry()
        v1 = registry.register(
            make_spec(version="1.0", indicators=(IndicatorSpec(code="A", name="A", weight=100.0),))
        )
        registry.register(
            make_spec(version="2.0", indicators=(IndicatorSpec(code="A", name="A", weight=50.0),))
        )

        assert registry.get("test", "1.0") is v1
        assert registry.get("test", "1.0").indicators[0].weight == 100.0
        assert registry.latest("test").version == "2.0"

    def test_ponyatnaya_oshibka_pri_otsutstvii_modeli(self) -> None:
        registry = ModelRegistry()
        registry.register(make_spec(version="1.0"))
        with pytest.raises(KeyError, match=r"test@1\.0"):
            registry.get("test", "9.9")

    def test_versiya_zapisyvaetsya_v_rezultat(self) -> None:
        result = evaluate(make_spec(version="3.1"), {"A": measured("A", 1.0)})
        assert result.model_version == "3.1"
        assert result.model_code == "test"
