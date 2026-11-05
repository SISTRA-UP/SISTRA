"""Rutas de la app propuestas.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', montaje.inicio, name='montaje'),

En las plantillas se enlazan con el nombre de la app:
{% url 'propuestas:montaje' %}.
"""

from django.urls import path  # noqa: F401

from .views import montaje  # noqa: F401  SISTRA-01
from .views import aprobacion  # noqa: F401  SISTRA-02

app_name = 'propuestas'

urlpatterns = [
    # SISTRA-01 · Montaje de propuesta – Trabajo Social

    # SISTRA-02 · Aprobación de propuesta
]
