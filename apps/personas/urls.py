"""Rutas de la app personas.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', registro_estudiantes.inicio, name='registro_estudiantes'),

En las plantillas se enlazan con el nombre de la app:
{% url 'personas:registro_estudiantes' %}.
"""

from django.urls import path  # noqa: F401

from .views import registro_estudiantes  # noqa: F401  SISTRA-10

app_name = 'personas'

urlpatterns = [
    # SISTRA-10 · Roles (registro de estudiantes)
    path('estudiantes/', registro_estudiantes.registrar, name='estudiantes'),
    path('estudiantes/csv/', registro_estudiantes.cargar_csv, name='estudiantes_csv'),
]
