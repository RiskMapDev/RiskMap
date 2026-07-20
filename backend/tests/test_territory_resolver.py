"""Тесты сопоставления названий территорий.

Написания взяты из фактических книг-источников, а не выдуманы: расхождения
зафиксированы аудитом в docs/audit/02 и docs/audit/03.
"""

from __future__ import annotations

import pytest

from app.services.territory_resolver import (
    ResolutionStatus,
    TerritoryResolver,
    build_report,
    normalize_territory_name,
)


class TestSvyortka:
    @pytest.mark.parametrize(
        ("raw", "ozhidaemoe"),
        [
            ("Талгарский район", "талгарский"),
            ("Талгарский р-н", "талгарский"),
            ("талгарский  Р-Н ", "талгарский"),
            ("Талгарский", "талгарский"),
        ],
    )
    def test_tip_edinitsy_ne_vliyaet(self, raw: str, ozhidaemoe: str) -> None:
        assert normalize_territory_name(raw) == ozhidaemoe

    def test_gorodskaya_administratsiya_svorachivaetsya(self) -> None:
        """«Қонаев Г.А.» и «Конаев» — одна территория."""
        assert normalize_territory_name("Қонаев Г.А.") == normalize_territory_name("Конаев")
        assert normalize_territory_name("г. Конаев") == normalize_territory_name("Конаев")

    def test_kazakhskaya_grafika_privoditsya_k_russkoy(self) -> None:
        assert normalize_territory_name("Еңбекшіқазақ ауданы") == "енбекшиказак"
        assert normalize_territory_name("Іле ауданы") == "иле"

    def test_yo_i_e_ne_razlichayutsya(self) -> None:
        assert normalize_territory_name("Жетісу") == normalize_territory_name("Жетису")

    def test_punktuatsiya_i_probely_ubirayutsya(self) -> None:
        assert normalize_territory_name("  «Илийский»  район ") == "илийский"

    def test_tip_vyrezaetsya_tolko_tselym_slovom(self) -> None:
        """Иначе «город» выкусится из середины названия и склеит разные единицы."""
        assert normalize_territory_name("Городовиковский район") == "городовиковский"

    def test_opechatki_ne_lechatsya_svyortkoy(self) -> None:
        """«Сарканский» и «Саркандский» обязаны остаться разными.

        Их разрешает таблица алиасов, где у написания есть источник. Если
        научить свёртку склеивать похожие строки, она начнёт склеивать и
        действительно разные территории.
        """
        assert normalize_territory_name("Сарканский") != normalize_territory_name("Саркандский")

    def test_pustaya_stroka_ne_padaet(self) -> None:
        assert normalize_territory_name("   ") == ""

    def test_nazvanie_iz_odnogo_tipa_ne_teryaetsya_polnostyu(self) -> None:
        """Если после вырезания типов ничего не осталось, вернётся исходная свёртка."""
        assert normalize_territory_name("район") != ""


class TestSopostavlenie:
    @pytest.fixture
    def resolver(self) -> TerritoryResolver:
        return TerritoryResolver(
            {
                "Талгарский район": "talgarskiy",
                "Талгарский р-н": "talgarskiy",
                "Илийский район": "iliyskiy",
                "Конаев": "konaev",
                "Қонаев Г.А.": "konaev",
                "Саркандский район": "sarkandskiy",
                "Сарканский": "sarkandskiy",
            }
        )

    def test_raznye_napisaniya_dayut_odnu_territoriyu(
        self, resolver: TerritoryResolver
    ) -> None:
        for napisanie in ("Талгарский район", "Талгарский р-н", "ТАЛГАРСКИЙ"):
            assert resolver.resolve(napisanie).territory_code == "talgarskiy"

    def test_opechatka_razreshaetsya_cherez_alias(self, resolver: TerritoryResolver) -> None:
        assert resolver.resolve("Сарканский").territory_code == "sarkandskiy"

    def test_kazakhskoe_napisanie_razreshaetsya(self, resolver: TerritoryResolver) -> None:
        assert resolver.resolve("Қонаев Г.А.").territory_code == "konaev"

    def test_neizvestnoe_nazvanie_ne_ugadyvaetsya(self, resolver: TerritoryResolver) -> None:
        """Похожесть не основание для привязки."""
        result = resolver.resolve("Талдыкорганский район")

        assert result.status is ResolutionStatus.NOT_FOUND
        assert result.territory_code is None
        assert "справочник" in result.reason

    def test_pustoe_znachenie_otlichaetsya_ot_ne_naydennogo(
        self, resolver: TerritoryResolver
    ) -> None:
        """«Территория не указана» и «название не опознано» — разные проблемы."""
        assert resolver.resolve(None).status is ResolutionStatus.EMPTY
        assert resolver.resolve("   ").status is ResolutionStatus.EMPTY
        assert resolver.resolve("нечто").status is ResolutionStatus.NOT_FOUND

    def test_neodnoznachnost_soobshchaetsya_a_ne_razreshaetsya_naugad(self) -> None:
        resolver = TerritoryResolver(
            {"Центральный район": "tsentralnyy-a", "Центральный р-н": "tsentralnyy-b"}
        )
        result = resolver.resolve("Центральный район")

        assert result.status is ResolutionStatus.AMBIGUOUS
        assert result.territory_code is None
        assert result.candidates == ("tsentralnyy-a", "tsentralnyy-b")

    def test_neodnoznachnye_napisaniya_vidny_zaranee(self) -> None:
        resolver = TerritoryResolver(
            {"Центральный район": "a", "Центральный р-н": "b", "Илийский район": "iliyskiy"}
        )
        assert resolver.ambiguous_names == ("центральный",)

    def test_require_padaet_ponyatno(self, resolver: TerritoryResolver) -> None:
        with pytest.raises(ValueError, match="Территория не определена"):
            resolver.resolve("Неизвестный район").require()

    def test_require_vozvrashchaet_kod(self, resolver: TerritoryResolver) -> None:
        assert resolver.resolve("Илийский район").require() == "iliyskiy"


class TestOtchyot:
    def test_nerazobrannoe_vidno_chislom(self) -> None:
        """Неопознанные территории обязаны быть заметны, а не теряться."""
        resolver = TerritoryResolver({"Илийский район": "iliyskiy"})
        resolutions = [
            resolver.resolve("Илийский район"),
            resolver.resolve("Илийский р-н"),
            resolver.resolve("Выдуманный район"),
            resolver.resolve(None),
        ]

        report = build_report(resolutions)

        assert report.total == 4
        assert report.resolved == 2
        assert len(report.not_found) == 1
        assert report.empty == 1
        assert report.unresolved == 2
        assert report.resolved_share == pytest.approx(0.5)

    def test_svodka_chitaema(self) -> None:
        resolver = TerritoryResolver({"Илийский район": "iliyskiy"})
        report = build_report([resolver.resolve("Илийский район"), resolver.resolve("Нечто")])

        assert "сопоставлено 1 из 2" in report.summary_ru()
        assert "не найдено 1" in report.summary_ru()

    def test_pustoy_otchyot_ne_delit_na_nol(self) -> None:
        assert build_report([]).resolved_share == 0.0
