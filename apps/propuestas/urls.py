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
    path('aprobacion/', aprobacion.bandeja, name='aprobacion'),
    path(
        'aprobacion/<int:id_propuesta>/detalle/',
        aprobacion.detalle_propuesta,
        name='detalle_propuesta',
    ),
    path(
        'aprobacion/detalle/<int:id_propuesta>/',
        aprobacion.detalle_propuesta,
    ),
    path(
        'aprobacion/<int:id_propuesta>/decidir/',
        aprobacion.cambiar_estado,
        name='cambiar_estado',
    ),
    path(
        'aprobacion/cambiar-estado/<int:id_propuesta>/',
        aprobacion.cambiar_estado,
    ),
    path(
        'aprobacion/<int:id_propuesta>/reactivar/',
        aprobacion.reactivar_propuesta,
        name='reactivar_propuesta',
    ),
    path(
        'aprobacion/reactivar/<int:id_propuesta>/',
        aprobacion.reactivar_propuesta,
    ),
    path('aprobacion/masivo/', aprobacion.accion_masiva, name='accion_masiva'),
    path(
        'aprobacion/<int:id_propuesta>/documento/',
        aprobacion.descargar_documento,
        name='descargar_documento',
    ),
    path(
        'aprobacion/descargar-documento/<int:id_propuesta>/',
        aprobacion.descargar_documento,
    ),
]
