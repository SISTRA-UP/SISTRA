"""Rutas de la app parametrizacion."""

from django.urls import path

from .views import documentos, parametrizacion  # noqa: F401  SISTRA-11

app_name = 'parametrizacion'

urlpatterns = [
    # SISTRA-11 · Parametrización
    path(
        'documentos/propuesta-estudiante/',
        documentos.DescargaPlantillaPropuestaEstudianteView.as_view(),
        name='plantilla_propuesta_estudiante',
    ),
]
