"""Rutas de la app informes.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', montaje.inicio, name='montaje'),

En las plantillas se enlazan con el nombre de la app:
{% url 'informes:montaje' %}.
"""

from django.urls import path  # noqa: F401

from .views import montaje  # noqa: F401  SISTRA-06
from .views import aprobacion  # noqa: F401  SISTRA-07
from .views import aprobacion_decisiones  # noqa: F401 SISTRA-07
from .views import aprobacion_masiva # noqa: F401 SISTRA-07

app_name = 'informes'

urlpatterns = [
    # SISTRA-06 · Montaje de informe – Trabajo Social

    # SISTRA-07 · Aprobación de informe
    path(
        "aprobacion/",
        aprobacion.bandeja,
        name="aprobacion",
    ),
    path(
        "aprobacion/<int:id_informe>/decidir/",
        aprobacion_decisiones.decidir,
        name="decidir",
    ),
     path(
        "aprobacion/masiva/",
        aprobacion_masiva.decidir_masivo,
        name="decidir_masivo",
    ),
]
