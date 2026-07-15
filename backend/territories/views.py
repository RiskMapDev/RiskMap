from rest_framework import viewsets

from .models import Territory
from .serializers import TerritorySerializer


class TerritoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Территории (только чтение) в формате GeoJSON.

    Query-параметры:
      ?level=oblast|rayon|settlement  — фильтр по уровню
      ?parent=<id>                    — районы конкретной области
      ?parent=null                    — только верхний уровень (области)
    """

    serializer_class = TerritorySerializer
    # Объектов немного (области + районы одной области) — отдаём без
    # пагинации, чтобы карта получала цельный FeatureCollection.
    pagination_class = None

    def get_queryset(self):
        qs = Territory.objects.all().order_by("level", "name_ru")

        level = self.request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)

        parent = self.request.query_params.get("parent")
        if parent == "null":
            qs = qs.filter(parent__isnull=True)
        elif parent:
            qs = qs.filter(parent_id=parent)

        return qs
