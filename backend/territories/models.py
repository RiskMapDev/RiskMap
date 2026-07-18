from django.conf import settings
from django.contrib.gis.db import models


class Territory(models.Model):
    """Административно-территориальная единица: область, район, нас. пункт.

    Основная таблица недели 1. Иерархия строится через self-FK `parent`
    (район -> область). Геометрия хранится в PostGIS (SRID 4326, WGS84).

    Значения `level` фиксированы как в ER-диаграмме проекта (oblast/rayon/
    settlement) — единый словарь для всей команды, не только backend.
    """

    class Level(models.TextChoices):
        OBLAST = "oblast", "Область"
        RAYON = "rayon", "Район"
        SETTLEMENT = "settlement", "Населённый пункт"

    # КАТО — официальный классификатор административно-территориальных
    # объектов РК. Ключ для сопоставления с данными stat.gov.kz и
    # budget.egov.kz. У районов пока не проставлен — см. data/SOURCE.md.
    kato_code = models.CharField(
        "КАТО", max_length=20, null=True, blank=True, db_index=True
    )
    # Технический идентификатор объекта в источнике границ (сейчас —
    # ID relation в OpenStreetMap). Нужен для повторной синхронизации:
    # по нему load_boundaries понимает, какую запись обновлять.
    external_id = models.CharField("ID источника", max_length=40, unique=True)

    name_ru = models.CharField("Наименование (рус.)", max_length=255)
    name_kz = models.CharField("Наименование (қаз.)", max_length=255, blank=True)
    level = models.CharField(
        "Уровень", max_length=20, choices=Level.choices, db_index=True
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        verbose_name="Родительская территория",
    )

    geometry = models.MultiPolygonField("Геометрия", srid=4326)

    population = models.BigIntegerField("Население", null=True, blank=True)
    area_km2 = models.FloatField("Площадь, км²", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Территория"
        verbose_name_plural = "Территории"
        ordering = ["level", "name_ru"]

    def __str__(self):
        return f"{self.get_level_display()}: {self.name_ru}"


class ThematicLayer(models.Model):
    """Реестр тематических слоёв карты (закупки, организации, бюджет...).

    Позволяет фронтенду динамически строить панель слоёв, а новые слои
    подключать без изменения кода — задел под недели 2-5.
    """

    code = models.SlugField("Код", max_length=50, unique=True)
    name_ru = models.CharField("Наименование", max_length=100)
    # Цвет маркера/заливки слоя на карте (ТЗ п.7.3 — цветовая индикация).
    color_hex = models.CharField(
        "Цвет (HEX)", max_length=7, default="#3388FF", blank=True
    )
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Активен", default=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Тематический слой"
        verbose_name_plural = "Тематические слои"
        ordering = ["sort_order", "name_ru"]

    def __str__(self):
        return self.name_ru


class GeoObject(models.Model):
    """Универсальный объект тематического слоя (закупка, организация и т.д.).

    Каркас под слои 2-5: конкретный набор полей у каждого слоя разный,
    поэтому специфичные данные складываем в JSON `attributes`. Схема
    зафиксирована уже на неделе 1 (включая external_id/source_system/
    imported_at), чтобы недели 2-5 писали данные без новых миграций.
    """

    layer = models.ForeignKey(
        ThematicLayer,
        on_delete=models.CASCADE,
        # related_name НЕ "objects": иначе обратный аксессор затенит
        # менеджер ThematicLayer.objects (Model.objects перестанет работать).
        related_name="geo_objects",
        verbose_name="Слой",
    )
    territory = models.ForeignKey(
        Territory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="geo_objects",
        verbose_name="Территория",
    )
    # Идентификатор объекта в исходной системе (напр. номер закупки на
    # goszakup) — ключ для повторного импорта/обновления без дублей.
    external_id = models.CharField("ID источника", max_length=100, blank=True)
    # Из какой системы пришли данные (goszakup, kgd, egov...) — ТЗ п.15.3
    # "фиксация источника и даты актуальности".
    source_system = models.CharField("Система-источник", max_length=50, blank=True)
    imported_at = models.DateTimeField("Дата импорта", null=True, blank=True)

    name = models.CharField("Наименование", max_length=500)
    attributes = models.JSONField("Атрибуты", default=dict, blank=True)
    geometry = models.GeometryField(
        "Геометрия", srid=4326, null=True, blank=True
    )
    risk_score = models.DecimalField(
        "Балл риска", max_digits=5, decimal_places=2, null=True, blank=True
    )
    risk_level = models.CharField("Уровень риска", max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Объект слоя"
        verbose_name_plural = "Объекты слоёв"

    def __str__(self):
        return self.name


class RiskFactor(models.Model):
    """Расшифровка расчёта риска: вклад одного индикатора в risk_score
    конкретного объекта (ТЗ п.14 — "пользователь должен видеть
    расшифровку расчёта").

    Таблица создаётся на неделе 1, реально используется с недели 2
    (закупки) — до этого пустая, без изменений структуры.
    """

    geo_object = models.ForeignKey(
        GeoObject,
        on_delete=models.CASCADE,
        related_name="risk_factors",
        verbose_name="Объект",
    )
    indicator_code = models.CharField("Код индикатора", max_length=50)
    indicator_name = models.CharField("Наименование индикатора", max_length=255)
    raw_value = models.DecimalField(
        "Исходное значение", max_digits=18, decimal_places=4, null=True, blank=True
    )
    weight = models.DecimalField("Вес", max_digits=4, decimal_places=2, default=1)
    contribution = models.DecimalField(
        "Вклад в итоговый балл", max_digits=5, decimal_places=2
    )
    calculated_at = models.DateTimeField("Рассчитано", auto_now_add=True)

    class Meta:
        verbose_name = "Фактор риска"
        verbose_name_plural = "Факторы риска (расшифровка расчёта)"
        ordering = ["-calculated_at"]

    def __str__(self):
        return f"{self.indicator_name} -> {self.geo_object_id}"


class ImportBatch(models.Model):
    """Журнал загрузки данных импорт-мастером (задел под задачу Мухаммеда)."""

    class Status(models.TextChoices):
        PENDING = "pending", "В обработке"
        DONE = "done", "Завершено"
        ERROR = "error", "Ошибка"

    file_name = models.CharField("Файл", max_length=255)
    source_name = models.CharField("Источник данных", max_length=100, blank=True)
    layer = models.ForeignKey(
        ThematicLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Слой",
    )
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.PENDING
    )
    total_rows = models.PositiveIntegerField("Всего строк", default=0)
    imported_rows = models.PositiveIntegerField("Загружено", default=0)
    error_rows = models.PositiveIntegerField("С ошибками", default=0)
    error_log = models.JSONField("Протокол ошибок", default=list, blank=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Кем загружено",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Загрузка данных"
        verbose_name_plural = "Загрузки данных"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.get_status_display()})"
