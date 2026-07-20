"""Маскирование ИИН и БИН по роли и журналирование раскрытия."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.access import AuditAction, AuditLogEntry, RoleCode, SensitiveDataAccess
from app.services import masking
from app.services.audit import RequestContext
from tests.conftest import UserFactory

pytestmark = pytest.mark.integration

#: ИИН из примера ТЗ. Значение вымышленное: контрольный разряд не проверяется,
#: и настоящих персональных данных в тестах быть не должно.
IIN = "840712300112"


class TestFormaMaski:
    def test_pervye_chetyre_i_poslednie_dve(self) -> None:
        """Та самая маска из ТЗ: 8407******12."""
        assert masking.mask_identifier(IIN) == "8407******12"

    def test_dlina_sokhranyaetsya(self) -> None:
        """По маске не должно быть видно, что номер короче или длиннее обычного."""
        assert len(masking.mask_identifier(IIN) or "") == len(IIN)

    def test_serdtsevina_zakryta_polnostyu(self) -> None:
        maska = masking.mask_identifier(IIN) or ""
        assert maska[4:-2] == "*" * 6
        assert IIN[4:-2] not in maska

    def test_bin_maskiruetsya_tem_zhe_pravilom(self) -> None:
        assert masking.mask_identifier("081040008218") == "0810******18"

    def test_probely_po_krayam_snimayutsya(self) -> None:
        assert masking.mask_identifier(f"  {IIN} ") == "8407******12"

    def test_pustoe_znachenie_dayot_nichego(self) -> None:
        assert masking.mask_identifier(None) is None
        assert masking.mask_identifier("") is None
        assert masking.mask_identifier("   ") is None

    def test_korotkoe_znachenie_maskiruetsya_tselikom(self) -> None:
        """Иначе у короткого номера открытыми оказались бы почти все знаки."""
        assert masking.mask_identifier("123456") == "******"
        assert masking.mask_identifier("12") == "**"


class TestStepeniDostupa:
    def test_polnyy_dostup_otdayot_znachenie(self) -> None:
        rezultat = masking.render_for_access(IIN, SensitiveDataAccess.FULL)
        assert rezultat.value == IIN
        assert rezultat.present

    def test_maskirovannyy_dostup_otdayot_masku(self) -> None:
        rezultat = masking.render_for_access(IIN, SensitiveDataAccess.MASKED)
        assert rezultat.value == "8407******12"
        assert rezultat.is_masked

    def test_skrytyy_dostup_ne_otdayot_znachenie_no_soobshchaet_o_nalichii(self) -> None:
        """ТЗ: HIDDEN — значение не отдаётся вовсе, вместо него признак наличия."""
        rezultat = masking.render_for_access(IIN, SensitiveDataAccess.HIDDEN)
        assert rezultat.value is None
        assert rezultat.present
        assert rezultat.is_hidden

    def test_otsutstvuyushchee_znachenie_odinakovo_dlya_vsekh_rezhimov(self) -> None:
        for access in SensitiveDataAccess:
            rezultat = masking.render_for_access(None, access)
            assert rezultat.value is None
            assert not rezultat.present

    def test_predstavlenie_dlya_api_razlichaet_net_i_nelzya(self) -> None:
        """Иначе пользователь примет закрытое поле за незаполненное."""
        skryto = masking.render_for_access(IIN, SensitiveDataAccess.HIDDEN).to_dict()
        pusto = masking.render_for_access(None, SensitiveDataAccess.HIDDEN).to_dict()

        assert skryto["value"] is None and skryto["present"] is True
        assert pusto["value"] is None and pusto["present"] is False


class TestMaskirovaniePoRolyam:
    """По одному случаю на каждую из четырёх ролей ТЗ."""

    def test_administrator_vidit_polnoe_znachenie(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        admin = make_user(RoleCode.ADMIN)
        assert masking.reveal(IIN, user=admin, session=db_session).value == IIN

    def test_analitik_vidit_masku(self, db_session: Session, make_user: UserFactory) -> None:
        analyst = make_user(RoleCode.ANALYST)
        assert masking.reveal(IIN, user=analyst, session=db_session).value == "8407******12"

    def test_rukovoditel_vidit_masku(self, db_session: Session, make_user: UserFactory) -> None:
        manager = make_user(RoleCode.MANAGER)
        assert masking.reveal(IIN, user=manager, session=db_session).value == "8407******12"

    def test_prosmotr_ne_vidit_nichego(self, db_session: Session, make_user: UserFactory) -> None:
        viewer = make_user(RoleCode.VIEWER)
        rezultat = masking.reveal(IIN, user=viewer, session=db_session)

        assert rezultat.value is None
        assert rezultat.present


class TestZhurnalirovanieRaskrytiya:
    @staticmethod
    def _zapisi(db_session: Session, user_id: object) -> list[AuditLogEntry]:
        return list(
            db_session.execute(
                select(AuditLogEntry)
                .where(AuditLogEntry.user_id == user_id)
                .where(AuditLogEntry.action == AuditAction.SENSITIVE_VIEW)
            )
            .scalars()
            .all()
        )

    def test_kazhdyy_prosmotr_polnogo_znacheniya_popadaet_v_zhurnal(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Требование ТЗ: раскрытие ИИН не проходит мимо журнала."""
        admin = make_user(RoleCode.ADMIN)

        masking.reveal(IIN, user=admin, session=db_session, entity_type="subsidy_recipient")

        zapisi = self._zapisi(db_session, admin.id)
        assert len(zapisi) == 1
        assert zapisi[0].details is not None
        assert zapisi[0].details["field"] == "iin"
        assert zapisi[0].entity_type == "subsidy_recipient"

    def test_dva_prosmotra_dayut_dve_zapisi(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """«Каждый» значит каждый: повторный просмотр — отдельное событие."""
        admin = make_user(RoleCode.ADMIN)

        masking.reveal(IIN, user=admin, session=db_session)
        masking.reveal(IIN, user=admin, session=db_session)

        assert len(self._zapisi(db_session, admin.id)) == 2

    def test_sam_iin_v_zhurnal_ne_popadaet(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Журнал фиксирует факт обращения, а не значение.

        Иначе журнал сам стал бы хранилищем персональных данных — с более
        широким кругом читателей, чем у исходной таблицы.
        """
        admin = make_user(RoleCode.ADMIN)

        masking.reveal(IIN, user=admin, session=db_session, entity_id="42")

        zapis = self._zapisi(db_session, admin.id)[0]
        assert IIN not in str(zapis.details)
        assert IIN not in str(zapis.entity_id)

    def test_prosmotr_maski_ne_zhurnaliruetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Иначе настоящие события утонут в шуме за первую же неделю."""
        analyst = make_user(RoleCode.ANALYST)

        masking.reveal(IIN, user=analyst, session=db_session)

        assert self._zapisi(db_session, analyst.id) == []

    def test_skrytoe_znachenie_ne_zhurnaliruetsya(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        viewer = make_user(RoleCode.VIEWER)

        masking.reveal(IIN, user=viewer, session=db_session)

        assert self._zapisi(db_session, viewer.id) == []

    def test_pustoe_znachenie_ne_schitaetsya_raskrytiem(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Раскрывать было нечего — событию неоткуда взяться."""
        admin = make_user(RoleCode.ADMIN)

        masking.reveal(None, user=admin, session=db_session)

        assert self._zapisi(db_session, admin.id) == []

    def test_obstoyatelstva_zaprosa_popadayut_v_zapis(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        admin = make_user(RoleCode.ADMIN)
        context = RequestContext(
            request_id="req-123", ip_address="10.1.2.3", user_agent="Тестовый клиент"
        )

        masking.reveal(IIN, user=admin, session=db_session, context=context)

        zapis = self._zapisi(db_session, admin.id)[0]
        assert zapis.request_id == "req-123"
        # Колонка INET возвращается драйвером как объект адреса, а не строкой.
        assert str(zapis.ip_address) == "10.1.2.3"
        assert zapis.user_agent == "Тестовый клиент"
        assert zapis.user_login == admin.login


class TestVyborkaTselikom:
    def test_odna_zapis_na_vsyu_vyborku_s_chislom_znacheniy(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        """Выгрузка таблицы не должна порождать двадцать тысяч событий об одном действии."""
        admin = make_user(RoleCode.ADMIN)

        rezultaty = masking.reveal_many(
            [IIN, "081040008218", None], user=admin, session=db_session, field="iin"
        )

        assert [r.value for r in rezultaty] == [IIN, "081040008218", None]
        zapisi = (
            db_session.execute(
                select(AuditLogEntry)
                .where(AuditLogEntry.user_id == admin.id)
                .where(AuditLogEntry.action == AuditAction.SENSITIVE_VIEW)
            )
            .scalars()
            .all()
        )
        assert len(zapisi) == 1
        assert zapisi[0].details is not None
        assert zapisi[0].details["count"] == 2

    def test_vyborka_bez_raskrytiya_zhurnal_ne_trogaet(
        self, db_session: Session, make_user: UserFactory
    ) -> None:
        analyst = make_user(RoleCode.ANALYST)

        rezultaty = masking.reveal_many([IIN, IIN], user=analyst, session=db_session)

        assert all(r.value == "8407******12" for r in rezultaty)
        zapisi = (
            db_session.execute(
                select(AuditLogEntry).where(AuditLogEntry.user_id == analyst.id)
            )
            .scalars()
            .all()
        )
        assert zapisi == []
