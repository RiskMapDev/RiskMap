from decimal import Decimal

from django.contrib.gis.geos import MultiPolygon, Polygon
from rest_framework.test import APITestCase

from territories.models import GeoObject, RiskFactor, Territory, ThematicLayer


def square(x, y, s=1.0):
    """Квадратный MultiPolygon для тестовой геометрии территории."""
    poly = Polygon(
        [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)], srid=4326
    )
    return MultiPolygon(poly, srid=4326)


class SubsidiesApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.oblast = Territory.objects.create(
            external_id="t-obl", name_ru="Тестовая область",
            level=Territory.Level.OBLAST, geometry=square(0, 0, 4),
        )
        cls.rayon1 = Territory.objects.create(
            external_id="t-r1", name_ru="Район А", parent=cls.oblast,
            level=Territory.Level.RAYON, geometry=square(0, 0),
        )
        cls.rayon2 = Territory.objects.create(
            external_id="t-r2", name_ru="Район Б (пустой)", parent=cls.oblast,
            level=Territory.Level.RAYON, geometry=square(2, 2),
        )
        cls.layer = ThematicLayer.objects.create(
            code="subsidies", name_ru="Субсидии", color_hex="#8B5CF6", sort_order=10,
        )

        # obj1: маленькая сумма, критический риск, активен в 2024
        cls.obj1 = GeoObject.objects.create(
            layer=cls.layer, territory=cls.rayon1, external_id="BIN1",
            name="ТОО Критик", source_system="subsidies_xlsx",
            risk_score=Decimal("80.00"), risk_level="critical",
            attributes={
                "paid_total": 1000.0,
                "by_year": {"2024": {"paid": 1000.0, "risk_score": 80.0,
                                     "risk_level": "critical"}},
            },
        )
        # obj2: большая сумма, низкий риск, активен в 2023
        cls.obj2 = GeoObject.objects.create(
            layer=cls.layer, territory=cls.rayon1, external_id="BIN2",
            name="АО Крупный", source_system="subsidies_xlsx",
            risk_score=Decimal("20.00"), risk_level="low",
            attributes={
                "paid_total": 9000.0,
                "by_year": {"2023": {"paid": 9000.0, "risk_score": 20.0,
                                     "risk_level": "low"}},
            },
        )
        RiskFactor.objects.create(
            geo_object=cls.obj1, indicator_code="concentration",
            indicator_name="Концентрация", raw_value=Decimal("0.5"),
            weight=Decimal("0.30"), contribution=Decimal("24.00"),
        )

    # ---- /api/layers/ ----
    def test_layers_list(self):
        r = self.client.get("/api/layers/")
        self.assertEqual(r.status_code, 200)
        codes = [x["code"] for x in r.json()]
        self.assertIn("subsidies", codes)

    # ---- /api/territories/risk/ ----
    def test_risk_geojson_weighted_and_no_holes(self):
        r = self.client.get(f"/api/territories/risk/?layer=subsidies&parent={self.oblast.id}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["type"], "FeatureCollection")
        # Оба района присутствуют — пустой не выкинут (нет дыр на карте).
        self.assertEqual(len(data["features"]), 2)
        props = {f["properties"]["name_ru"]: f["properties"] for f in data["features"]}

        # Взвешенный риск Района А = (80*1000 + 20*9000)/10000 = 26.0
        self.assertAlmostEqual(props["Район А"]["risk_score"], 26.0, places=2)
        self.assertEqual(props["Район А"]["risk_level"], "low")
        self.assertEqual(props["Район А"]["objects_count"], 2)
        self.assertEqual(props["Район А"]["high_risk_count"], 1)  # obj1 critical
        self.assertAlmostEqual(props["Район А"]["risk_exposure"], 2600.0, places=2)

        # Пустой район — level=null, но фича есть и геометрия отдана.
        self.assertIsNone(props["Район Б (пустой)"]["risk_level"])
        self.assertEqual(props["Район Б (пустой)"]["objects_count"], 0)
        self.assertIsNotNone(props["Район Б (пустой)"]["id"])

    def test_risk_year_filter_recomputes(self):
        r = self.client.get(
            f"/api/territories/risk/?layer=subsidies&parent={self.oblast.id}&year=2024"
        )
        props = {f["properties"]["name_ru"]: f["properties"] for f in r.json()["features"]}
        # В 2024 активен только obj1 -> взвешенный риск = 80, critical.
        self.assertAlmostEqual(props["Район А"]["risk_score"], 80.0, places=2)
        self.assertEqual(props["Район А"]["risk_level"], "critical")
        self.assertEqual(props["Район А"]["objects_count"], 1)

    def test_risk_level_filter(self):
        r = self.client.get(
            f"/api/territories/risk/?layer=subsidies&parent={self.oblast.id}"
            f"&risk_level=critical"
        )
        props = {f["properties"]["name_ru"]: f["properties"] for f in r.json()["features"]}
        # Только критические объекты -> в Районе А остаётся obj1, риск=80.
        self.assertAlmostEqual(props["Район А"]["risk_score"], 80.0, places=2)
        self.assertEqual(props["Район А"]["objects_count"], 1)

    # ---- /api/dashboard/ ----
    def test_dashboard_oblast(self):
        r = self.client.get(f"/api/dashboard/?layer=subsidies&territory={self.oblast.id}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["territory"]["level"], "oblast")
        self.assertEqual(data["objects_count"], 2)
        self.assertAlmostEqual(data["paid_total"], 10000.0, places=2)
        self.assertEqual(data["by_level"]["critical"], 1)
        self.assertEqual(data["by_level"]["low"], 1)
        # top_exposure: obj2 (1800) выше obj1 (800) — материальность.
        self.assertEqual(data["top_exposure"][0]["external_id"], "BIN2")
        # top_risk: obj1 (80) выше obj2 (20).
        self.assertEqual(data["top_risk"][0]["external_id"], "BIN1")

    def test_dashboard_rayon(self):
        r = self.client.get(f"/api/dashboard/?layer=subsidies&territory={self.rayon1.id}")
        data = r.json()
        self.assertEqual(data["territory"]["level"], "rayon")
        self.assertEqual(data["objects_count"], 2)

    # ---- /api/geo-objects/ ----
    def test_geo_objects_list_paginated(self):
        r = self.client.get("/api/geo-objects/?layer=subsidies")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("results", data)  # пагинация включена
        self.assertEqual(data["count"], 2)

    def test_geo_objects_order_by_paid(self):
        r = self.client.get("/api/geo-objects/?layer=subsidies&ordering=-paid_total")
        results = r.json()["results"]
        self.assertEqual(results[0]["external_id"], "BIN2")  # 9000 первым

    def test_geo_objects_filter_risk_level(self):
        r = self.client.get("/api/geo-objects/?layer=subsidies&risk_level=critical")
        results = r.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["external_id"], "BIN1")

    def test_geo_objects_search(self):
        r = self.client.get("/api/geo-objects/?search=Крупный")
        results = r.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["external_id"], "BIN2")

    def test_geo_object_detail_has_risk_factors(self):
        r = self.client.get(f"/api/geo-objects/{self.obj1.id}/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["risk_factors"]), 1)
        self.assertEqual(data["risk_factors"][0]["indicator_code"], "concentration")
        self.assertIn("attributes", data)
