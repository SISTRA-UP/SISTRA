"""Rutas de la app dashboard (SISTRA-14)."""

from django.urls import path

from .views import dashboard

app_name = 'dashboard'

urlpatterns = [
    # SISTRA-14 · Dashboard
    path('', dashboard.inicio, name='inicio'),
    path('estudiante/', dashboard.dashboard_estudiante, name='estudiante'),
    path('director/', dashboard.dashboard_director, name='director'),
    path('administrador/', dashboard.dashboard_administrador, name='administrador'),
]