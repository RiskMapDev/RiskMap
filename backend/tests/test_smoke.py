"""Дымовые тесты каркаса: приложение поднимается, база отвечает, PostGIS живой."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db.session import get_engine
from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def test_health_ne_trogaet_bazu(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_otdayotsya_po_versionirovannomu_puti(client: TestClient) -> None:
    settings = get_settings()
    response = client.get(f"{settings.api_prefix}/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"] == "0.1.0"


def test_id_zaprosa_vozvrashchaetsya(client: TestClient) -> None:
    """Сквозной идентификатор нужен, чтобы связать запись в логе с обращением.

    Значение заголовка — только ASCII: HTTP этого требует, и httpx падает на
    кириллице ещё до отправки.
    """
    response = client.get("/health", headers={"X-Request-ID": "check-123"})
    assert response.headers["X-Request-ID"] == "check-123"


def test_id_zaprosa_generiruetsya_esli_ne_peredan(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers.get("X-Request-ID")


class TestNastroyki:
    def test_v_prod_pustoy_sekret_zapreshchyon(self) -> None:
        """Забытый JWT_SECRET в проде обязан ронять старт, а не подставляться молча."""
        with pytest.raises(ValueError, match="JWT_SECRET"):
            Settings(environment="prod", jwt_secret="")

    def test_v_dev_sekret_generiruetsya(self) -> None:
        settings = Settings(environment="dev", jwt_secret="")
        assert len(settings.jwt_secret) >= 32

    def test_dva_vyzova_dayut_raznye_sekrety(self) -> None:
        """Сгенерированный по умолчанию секрет не должен быть предсказуемым."""
        assert Settings(environment="dev").jwt_secret != Settings(environment="dev").jwt_secret


@pytest.mark.integration
class TestBazaDannykh:
    """Требуют живого кластера на порту 5433."""

    def test_soedinenie_est(self) -> None:
        with get_engine().connect() as conn:
            assert conn.execute(text("select 1")).scalar_one() == 1

    def test_postgis_vklyuchyon(self) -> None:
        with get_engine().connect() as conn:
            version = conn.execute(text("select postgis_version()")).scalar_one()
        assert "USE_GEOS=1" in version
        assert "USE_PROJ=1" in version

    def test_geografiya_schitaet_ploshchad(self) -> None:
        """Площадь считается на сфероиде, а не в градусах.

        Это не формальность: расчёт в градусах на широте 43° занижает площадь
        примерно на четверть, и все производные показатели поедут.
        """
        with get_engine().connect() as conn:
            area_km2 = conn.execute(
                text(
                    "select ST_Area(ST_GeomFromText("
                    "'POLYGON((76 43,77 43,77 44,76 44,76 43))', 4326)::geography) / 1e6"
                )
            ).scalar_one()
        assert 8900 < area_km2 < 9100

    def test_gist_indeks_dostupen(self) -> None:
        """Без GiST карта не уложится в норматив ТЗ по времени отклика."""
        query = text("select count(*) from pg_am where amname='gist'")
        with get_engine().connect() as conn:
            found = conn.execute(query).scalar_one()
        assert found == 1

    def test_ready_otvechaet_gotovnostyu(self, client: TestClient) -> None:
        response = client.get("/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
        assert "USE_GEOS=1" in body["checks"]["postgis"]
