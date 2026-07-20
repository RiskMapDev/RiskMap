"""Тесты каталога тематических слоёв.

Проверяется главное: слой не притворяется доступным там, где данных нет,
и причина недоступности доходит до пользователя текстом.
"""

from __future__ import annotations

import pytest

from app.db.models.territory import TerritoryLevel
from app.services.layers import (
    LAYERS,
    LayerRenderKind,
    get_layer,
    layers_for_level,
    mappable_layers,
)


class TestSostavKataloga:
    def test_slolov_desyat(self) -> None:
        """Счётчик «(5 / 10)» на референсе подразумевает десять слоёв."""
        assert len(LAYERS) == 10

    def test_kody_unikalny(self) -> None:
        codes = [layer.code for layer in LAYERS]
        assert len(codes) == len(set(codes))

    def test_u_kazhdogo_sloya_est_opisanie(self) -> None:
        for layer in LAYERS:
            assert layer.title.strip()
            assert layer.description.strip()

    def test_neizvestnyy_sloy_daet_ponyatnuyu_oshibku(self) -> None:
        with pytest.raises(KeyError, match="не описан"):
            get_layer("выдуманный")


class TestUrovniDostupnosti:
    def test_byudzhet_tolko_na_urovne_oblasti(self) -> None:
        """Слой 8.3 общереспубликанский, разбивки по районам в источнике нет."""
        budget = get_layer("budget")

        assert budget.available_at(TerritoryLevel.REGION)
        assert not budget.available_at(TerritoryLevel.DISTRICT)

    def test_zakupki_i_subsidii_tolko_na_urovne_rayona(self) -> None:
        for code in ("procurement", "subsidies"):
            layer = get_layer(code)
            assert layer.available_at(TerritoryLevel.DISTRICT)
            assert not layer.available_at(TerritoryLevel.REGION)

    def test_gchp_ne_vyvoditsya_na_rayonnyy_uroven(self) -> None:
        """У проектов ГЧП в источнике указана только область.

        Приписать проект району значило бы выдумать данные, которых нет.
        """
        ppp = get_layer("infrastructure_ppp")

        assert ppp.available_at(TerritoryLevel.REGION)
        assert not ppp.available_at(TerritoryLevel.DISTRICT)

    def test_organizatsii_ne_vyvodyatsya_na_kartu_voobshche(self) -> None:
        """В книге 8.7 нет ни района, ни адреса, ни координат, ни КАТО."""
        orgs = get_layer("organizations")

        assert orgs.render is LayerRenderKind.NONE
        assert orgs.levels == frozenset()
        assert not orgs.available_at(TerritoryLevel.REGION)
        assert not orgs.available_at(TerritoryLevel.DISTRICT)

    def test_na_urovne_oblasti_dostupen_byudzhet_no_ne_zakupki(self) -> None:
        codes = {layer.code for layer in layers_for_level(TerritoryLevel.REGION)}

        assert "budget" in codes
        assert "infrastructure_ppp" in codes
        assert "procurement" not in codes
        assert "subsidies" not in codes

    def test_na_urovne_rayona_dostupny_zakupki_no_ne_byudzhet(self) -> None:
        codes = {layer.code for layer in layers_for_level(TerritoryLevel.DISTRICT)}

        assert "procurement" in codes
        assert "subsidies" in codes
        assert "budget" not in codes

    def test_gorod_ravnopraven_rayonu(self) -> None:
        """Город областного значения — единица того же уровня, что и район.

        Конаев и Алатау не должны выпадать из районных слоёв.
        """
        district_codes = {layer.code for layer in layers_for_level(TerritoryLevel.DISTRICT)}
        city_codes = {layer.code for layer in layers_for_level(TerritoryLevel.CITY)}

        assert district_codes == city_codes


class TestPrichinaNedostupnosti:
    def test_prichina_soobshchaetsya_tekstom(self) -> None:
        """Пустая заливка неотличима от нулевого риска — нужен текст."""
        reason = get_layer("budget").unavailability_reason(TerritoryLevel.DISTRICT)

        assert reason
        assert "область" in reason

    def test_dostupnyy_sloy_ne_daet_prichiny(self) -> None:
        assert get_layer("budget").unavailability_reason(TerritoryLevel.REGION) == ""

    def test_dlya_sloya_bez_geografii_prichina_soderzhatelna(self) -> None:
        """Пользователю называется и причина, и где искать эти объекты вместо карты."""
        reason = get_layer("organizations").unavailability_reason(TerritoryLevel.DISTRICT)

        assert "координат" in reason
        assert "карту" in reason
        assert "списке" in reason

    def test_ogranicheniya_pokrytiya_opisany_u_vsekh_chastichnykh_sloyov(self) -> None:
        """Каждое ограничение выборки должно быть предъявлено пользователю."""
        for code in (
            "procurement",
            "subsidies",
            "infrastructure_ppp",
            "infrastructure_expertise",
            "organizations",
            "budget",
        ):
            assert get_layer(code).coverage_note.strip(), code

    def test_vyborka_zakupok_pomechena_kak_ne_sploshnaya(self) -> None:
        """355 договоров 26 поставщиков — целевой срез, а не все закупки региона."""
        note = get_layer("procurement").coverage_note
        assert "не сплошная выборка" in note

    def test_edinitsa_ucheta_ekspertizy_ogovorena(self) -> None:
        note = get_layer("infrastructure_expertise").coverage_note
        assert "заключение" in note


class TestKarta:
    def test_na_kartu_vyvodyatsya_devyat_sloyov(self) -> None:
        assert len(mappable_layers()) == len(LAYERS) - 1

    def test_organizatsii_ne_popadayut_v_kartografiruemye(self) -> None:
        assert "organizations" not in {layer.code for layer in mappable_layers()}

    def test_po_umolchaniyu_vklyucheny_tri_sloya(self) -> None:
        """На референсе включены административный, соц-экономический и бюджетный."""
        enabled = {layer.code for layer in LAYERS if layer.enabled_by_default}
        assert enabled == {"administrative", "population", "budget"}
