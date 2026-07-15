from django.contrib.gis.db import models


class Territory(models.Model):
    """Административно-территориальная единица: область или район.

    Основная таблица недели 1. Иерархия строится через self-FK `parent`
    (район -> область). Геометрия хранится в PostGIS (SRID 4326, WGS84).
    """

    class Level(models.TextChoices):
        COUNTRY = "country", "Страна"
        REGION = "region", "Область"
        DISTRICT = "district", "Район"

    # КАТО — официальный классификатор административно-территориальных
    # объектов РК. В исходных данных GADM его нет, поэтому nullable:
    # у областей проставляем реальные коды, у районов пока пусто.
    kato_code = models.CharField(
        "КАТО", max_length=20, null=True, blank=True, db_index=True
    )
    # Технический идентификатор объекта в источнике границ (сейчас —
    # ID relation в OpenStreetMap). Нужен для повторной синхронизации:
    # по нему load_boundaries понимает, какую запись обновлять.
    external_id = models.CharField("ID источника", max_length=40, unique=True)

    name = models.CharField("Наименование", max_length=255)
    name_en = models.CharField(
        "Наименование (лат.)", max_length=255, blank=True
    )
    level = models.CharField(
        "Уровень", max_length=16, choices=Level.choices, db_index=True
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
        ordering = ["level", "name"]

    def __str__(self):
        return f"{self.get_level_display()}: {self.name}"


class ThematicLayer(models.Model):
    """Реестр тематических слоёв карты (закупки, организации, бюджет...).

    Позволяет фронтенду динамически строить панель слоёв, а новые слои
    подключать без изменения кода — задел под недели 2-5.
    """

    code = models.SlugField("Код", max_length=64, unique=True)
    name = models.CharField("Наименование", max_length=255)
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Активен", default=True)
    order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Тематический слой"
        verbose_name_plural = "Тематические слои"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class GeoObject(models.Model):
    """Универсальный объект тематического слоя (закупка, организация и т.д.).

    Каркас под слои 2-5: конкретный набор полей у каждого слоя разный,
    поэтому специфичные данные складываем в JSON `attributes`.
    """

    layer = models.ForeignKey(
        ThematicLayer,
        on_delete=models.CASCADE,
        related_name="objects",
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
    name = models.CharField("Наименование", max_length=512)
    attributes = models.JSONField("Атрибуты", default=dict, blank=True)
    geometry = models.GeometryField(
        "Геометрия", srid=4326, null=True, blank=True
    )
    risk_score = models.FloatField("Балл риска", null=True, blank=True)
    risk_level = models.CharField(
        "Уровень риска", max_length=16, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Объект слоя"
        verbose_name_plural = "Объекты слоёв"

    def __str__(self):
        return self.name


class RiskFactor(models.Model):
    """Индикатор риска: вес и порог для расчёта интегральной оценки.

    Каркас под модуль оценки риска (единый стандарт уровней для всех слоёв).
    """

    layer = models.ForeignKey(
        ThematicLayer,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="risk_factors",
        verbose_name="Слой",
    )
    code = models.SlugField("Код", max_length=64, unique=True)
    name = models.CharField("Наименование", max_length=255)
    description = models.TextField("Описание", blank=True)
    weight = models.FloatField("Вес", default=1.0)
    threshold = models.FloatField("Порог", null=True, blank=True)

    class Meta:
        verbose_name = "Индикатор риска"
        verbose_name_plural = "Индикаторы риска"

    def __str__(self):
        return self.name


class ImportBatch(models.Model):
    """Журнал загрузки данных импорт-мастером (задел под задачу Мухаммеда)."""

    class Status(models.TextChoices):
        PENDING = "pending", "В обработке"
        DONE = "done", "Завершено"
        ERROR = "error", "Ошибка"

    file_name = models.CharField("Файл", max_length=512)
    layer = models.ForeignKey(
        ThematicLayer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="Слой",
    )
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    rows_total = models.PositiveIntegerField("Всего строк", default=0)
    rows_ok = models.PositiveIntegerField("Загружено", default=0)
    rows_error = models.PositiveIntegerField("С ошибками", default=0)
    log = models.TextField("Протокол", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Загрузка данных"
        verbose_name_plural = "Загрузки данных"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} ({self.get_status_display()})"
