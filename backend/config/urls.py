from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view()),
    path('api/token/refresh/', TokenRefreshView.as_view()),
    path('api/accounts/', include('accounts.urls')),
    path('api/regions/', include('regions.urls')),
    path('api/budget/', include('budget.urls')),
    path('api/procurement/', include('procurement.urls')),
    path('api/construction/', include('construction.urls')),
    path('api/risks/', include('risks.urls')),
    path('api/agro/', include('agro.urls')),
    path('api/entities/', include('entities.urls')),
    path('api/osms/', include('osms.urls')),
    path('api/subsoil/', include('subsoil.urls')),
    path('api/integrations/', include('integrations.urls')),
    path('api/analytics/', include('analytics.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
