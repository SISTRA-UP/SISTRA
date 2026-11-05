"""Rutas de la app reportes.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', reportes.inicio, name='reportes'),

En las plantillas se enlazan con el nombre de la app:
{% url 'reportes:reportes' %}.
"""

from django.urls import path  # noqa: F401

from .views import reportes  # noqa: F401  SISTRA-12

app_name = 'reportes'

urlpatterns = [
    # SISTRA-12 · Reportes
]
