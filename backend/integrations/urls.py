from django.urls import path
from .views import integration_status, sync_goszakup, set_token

urlpatterns = [
    path('status/',        integration_status),
    path('sync/goszakup/', sync_goszakup),
    path('set-token/',     set_token),
]
