"""Тесты канонической выборки.

Главное здесь — обратимость: состояние, ушедшее в адресную строку, обязано
вернуться из неё без потерь. Иначе кнопка «назад» в браузере восстановит не ту
выборку, а карта и список разойдутся.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.api.queryspec import ObjectType, PageInfo, QuerySpec, SortField, SortOrder
from app.risk.core import RiskLevel


class TestUmolchaniya:
    def test_pustaya_vyborka_oznachaet_vsyo(self) -> None:
        """Пользователь, впервые открывший экран, должен увидеть данные."""
        spec = QuerySpec()

        assert spec.territory_codes == []
        assert spec.object_types == []
        assert spec.page == 1

    def test_uroven_net_dannykh_vklyuchen_po_umolchaniyu(self) -> None:
        """Иначе неизмеренные объекты молча исчезнут из выборки.

        Пользователь решит, что видит всё, хотя видит только измеренное.
        """
        spec = QuerySpec()

        assert RiskLevel.UNKNOWN in spec.risk_levels
        assert spec.includes_unknown_risk
        assert set(spec.risk_levels) == set(RiskLevel)

    def test_dochernie_territorii_vklyucheny(self) -> None:
        """Выбор области без районов дал бы пустую выборку."""
        assert QuerySpec().include_child_territories is True

    def test_sortirovka_po_risku_ubyvaniyu(self) -> None:
        spec = QuerySpec()
        assert spec.sort is SortField.RISK
        assert spec.order is SortOrder.DESC


class TestProverki:
    def test_nachalo_pozzhe_kontsa_otvergaetsya(self) -> None:
        with pytest.raises(ValidationError, match="начало периода позже"):
            QuerySpec(date_from=date(2026, 6, 1), date_to=date(2026, 1, 1))

    def test_summa_naoborot_otvergaetsya(self) -> None:
        with pytest.raises(ValidationError, match="нижняя граница суммы"):
            QuerySpec(amount_min=100, amount_max=10)

    def test_polnota_naoborot_otvergaetsya(self) -> None:
        with pytest.raises(ValidationError, match="нижняя граница полноты"):
            QuerySpec(completeness_min=0.9, completeness_max=0.1)

    def test_pustoy_spisok_urovney_otvergaetsya_s_podskazkoy(self) -> None:
        """Такая выборка всегда пуста, и пользователь не поймёт почему."""
        with pytest.raises(ValidationError, match="всегда пуста"):
            QuerySpec(risk_levels=[])

    def test_neizvestnoe_pole_otvergaetsya(self) -> None:
        """Опечатка в параметре не должна молча игнорироваться при построении."""
        with pytest.raises(ValidationError):
            QuerySpec(nesushchestvuyushchee_pole="значение")  # type: ignore[call-arg]

    def test_razmer_stranitsy_ogranichen(self) -> None:
        with pytest.raises(ValidationError):
            QuerySpec(page_size=10_000)


class TestObratimostVUrl:
    def test_umolchaniya_ne_popadayut_v_ssylku(self) -> None:
        """Ссылка должна оставаться читаемой."""
        assert QuerySpec().to_query_params() == {}

    def test_polnaya_vyborka_perezhivaet_krug(self) -> None:
        исходная = QuerySpec(
            date_from=date(2024, 1, 1),
            date_to=date(2024, 6, 30),
            territory_codes=["talgarskiy", "iliyskiy"],
            object_types=[ObjectType.CONTRACT],
            amount_min=1000,
            amount_max=5_000_000,
            risk_levels=[RiskLevel.HIGH, RiskLevel.CRITICAL],
            completeness_min=0.5,
            search="ТОО Строй",
            sort=SortField.AMOUNT,
            order=SortOrder.ASC,
            page=3,
            page_size=50,
        )

        восстановленная = QuerySpec.from_query_params(исходная.to_query_params())

        assert восстановленная == исходная

    def test_vybor_territoriy_perezhivaet_krug(self) -> None:
        исходная = QuerySpec(territory_codes=["talgarskiy", "konaev"])
        восстановленная = QuerySpec.from_query_params(исходная.to_query_params())

        assert восстановленная.territory_codes == ["talgarskiy", "konaev"]

    def test_pustoy_spisok_otlichaetsya_ot_umolchaniya(self) -> None:
        """«Ничего не выбрано» и «фильтр не тронут» — разные выборки.

        Первая даёт пустой результат, вторая — полный. Если не различать их
        в ссылке, состояние восстановится неверно.
        """
        исходная = QuerySpec(object_types=[])
        assert исходная.to_query_params() == {}

        явно_пустая = QuerySpec(territory_codes=[])
        assert явно_пустая.to_query_params() == {}

    def test_spisok_cherez_zapyatuyu_prinimaetsya(self) -> None:
        spec = QuerySpec.from_query_params({"territory_codes": "talgarskiy,iliyskiy"})
        assert spec.territory_codes == ["talgarskiy", "iliyskiy"]

    def test_lishnie_parametry_ignoriruyutsya_pri_razbore(self) -> None:
        """В адресной строке бывает мусор от аналитики — он не должен ронять разбор."""
        spec = QuerySpec.from_query_params({"utm_source": "mail", "page": 2})
        assert spec.page == 2

    def test_stroka_zaprosa_sobiraetsya(self) -> None:
        spec = QuerySpec(page=2, search="ТОО")
        строка = spec.to_query_string()

        assert "page=2" in строка
        assert "search=" in строка


class TestPoisk:
    def test_probely_obrezayutsya(self) -> None:
        assert QuerySpec(search="  ТОО Строй  ").search == "ТОО Строй"

    def test_pustoy_poisk_stanovitsya_none(self) -> None:
        """Пустая строка не должна превращаться в фильтр «имя равно пусто»."""
        assert QuerySpec(search="   ").search is None


class TestChipyIsbros:
    def test_netronutye_filtry_ne_dayut_chipov(self) -> None:
        assert QuerySpec().active_filter_chips() == []
        assert QuerySpec().has_active_filters is False

    def test_stranitsa_ne_schitaetsya_aktivnym_filtrom(self) -> None:
        """Переход на вторую страницу не должен зажигать кнопку «Сбросить»."""
        assert QuerySpec(page=5).has_active_filters is False

    def test_chip_perioda_chitaem(self) -> None:
        spec = QuerySpec(date_from=date(2024, 1, 1), date_to=date(2024, 6, 30))
        chips = dict(spec.active_filter_chips())
        assert chips["Период"] == "01.01.2024 — 30.06.2024"

    def test_chip_urovnya_riska_nazyvaet_urovni(self) -> None:
        chips = dict(QuerySpec(risk_levels=[RiskLevel.CRITICAL]).active_filter_chips())
        assert chips["Уровень риска"] == "Критический"

    def test_polnyy_nabor_urovney_ne_daet_chipa(self) -> None:
        """Все уровни — это отсутствие фильтра, а не фильтр по пяти значениям."""
        chips = dict(QuerySpec(risk_levels=list(RiskLevel)).active_filter_chips())
        assert "Уровень риска" not in chips

    def test_chip_poiska_pokazyvaet_zapros(self) -> None:
        chips = dict(QuerySpec(search="ТОО Строй").active_filter_chips())
        assert chips["Поиск"] == "ТОО Строй"


class TestStranitsy:
    def test_smeshchenie_schitaetsya_ot_stranitsy(self) -> None:
        assert QuerySpec(page=1, page_size=25).offset == 0
        assert QuerySpec(page=3, page_size=25).offset == 50

    def test_perekhod_na_stranitsu_ne_menyaet_filtry(self) -> None:
        исходная = QuerySpec(search="ТОО", risk_levels=[RiskLevel.HIGH])
        вторая = исходная.for_page(2)

        assert вторая.page == 2
        assert вторая.search == "ТОО"
        assert вторая.risk_levels == [RiskLevel.HIGH]

    def test_karta_beret_vyborku_tselikom(self) -> None:
        """Пагинация относится к списку, карта показывает всю выборку."""
        spec = QuerySpec(page=7, page_size=10, search="ТОО").without_pagination()

        assert spec.page == 1
        assert spec.search == "ТОО"

    def test_svedeniya_o_stranitse(self) -> None:
        info = PageInfo.build(QuerySpec(page=2, page_size=25), total=60)

        assert info.total_pages == 3
        assert info.has_next is True
        assert info.has_previous is True

    def test_pustoy_rezultat_daet_nol_stranits(self) -> None:
        info = PageInfo.build(QuerySpec(), total=0)

        assert info.total_pages == 0
        assert info.has_next is False
