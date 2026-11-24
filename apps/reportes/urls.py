
"""Rutas de la app reportes."""

from django.urls import path

from .views import reportes

app_name = 'reportes'

urlpatterns = [
    path(
        '',
        reportes.reportes,
        name='reportes',
    ),
]
