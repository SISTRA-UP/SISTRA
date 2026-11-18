"""Rutas de la app dashboard (SISTRA-14)."""

from django.urls import path

from .views import admo, dashboard, docente

app_name = 'dashboard'

urlpatterns = [
    # SISTRA-14 · Dashboard
    path('', dashboard.inicio, name='inicio'),
    path('estudiante/', dashboard.dashboard_estudiante, name='estudiante'),
    path('docente/', docente.docente, name='docente'),
    path('director/', docente.docente, name='director'),
    path(
        'notificaciones/<int:id_notificacion>/abrir/',
        docente.abrir_notificacion,
        name='abrir_notificacion',
    ),
    path('administracion/', admo.admo, name='admo'),
    path('administrador/', admo.admo, name='administrador'),
]