"""Rutas de la app cargue_up.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', cargue_propuesta.inicio, name='cargue_propuesta'),

En las plantillas se enlazan con el nombre de la app:
{% url 'cargue_up:cargue_propuesta' %}.
"""

from django.urls import path  # noqa: F401

from .views import cargue_propuesta  # noqa: F401  SISTRA-03
from .views import aviso_propuesta  # noqa: F401  SISTRA-04
from .views import verificacion_propuesta  # noqa: F401  SISTRA-05
from .views import aviso_informe  # noqa: F401  SISTRA-08
from .views import verificacion_informe  # noqa: F401  SISTRA-09

app_name = 'cargue_up'

urlpatterns = [
    # SISTRA-03 · Cargue al sistema de UP
    path('', cargue_propuesta.inicio, name='cargue_propuesta'),
    path('descargar/<int:id_propuesta>/', cargue_propuesta.descargar_propuesta, name='descargar_propuesta'),
    path('notificar/<int:id_propuesta>/', cargue_propuesta.notificar_cargue, name='notificar_cargue'),
    path('ir-up/<int:id_propuesta>/', cargue_propuesta.ir_a_up, name='ir_a_up'),

    # SISTRA-04 · Notificación de cargue UP

    # SISTRA-05 · Notificación de cargue UP – Director

    # SISTRA-08 · Notificación de cargue UP (informe)

    # SISTRA-09 · Notificación de cargue UP – Director (informe)
]
