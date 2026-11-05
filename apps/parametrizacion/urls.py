"""Rutas de la app parametrizacion.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', parametrizacion.inicio, name='parametrizacion'),

En las plantillas se enlazan con el nombre de la app:
{% url 'parametrizacion:parametrizacion' %}.
"""

from django.urls import path  # noqa: F401

from .views import parametrizacion  # noqa: F401  SISTRA-11

app_name = 'parametrizacion'

urlpatterns = [
    # SISTRA-11 · Parametrización
]
