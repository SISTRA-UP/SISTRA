"""Rutas de la app cargue_up.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', cargue_propuesta.inicio, name='cargue_propuesta'),

En las plantillas se enlazan con el nombre de la app:
{% url 'cargue_up:cargue_propuesta' %}.
"""

from django.urls import path  # noqa: F401

from .views import cargue_propuesta  # noqa: F401  SISTRA-03
from .views import aviso_propuesta  # noqa: F401  SISTRA-04
from apps.cargue_up.views import verificacion_propuesta # noqa: F401  SISTRA-05
from .views import aviso_informe  # noqa: F401  SISTRA-08
from .views import verificacion_informe  # noqa: F401  SISTRA-09

app_name = 'cargue_up'

urlpatterns = [
    # SISTRA-03 · Cargue al sistema de UP
    path('', cargue_propuesta.inicio, name='cargue_propuesta'),
    path('descargar/<int:id_propuesta>/', cargue_propuesta.descargar_propuesta, name='descargar_propuesta'),
    path('ir-up/<int:id_propuesta>/', cargue_propuesta.ir_a_up, name='ir_a_up'),

    # SISTRA-04 · Notificación de cargue UP
    path(
        'avisar/propuesta/<int:id_propuesta>/',
        aviso_propuesta.confirmacion,
        name='aviso_propuesta_confirmacion',
    ),
    path(
        'avisar/propuesta/<int:id_propuesta>/registrar/',
        aviso_propuesta.registrar,
        name='aviso_propuesta_registrar',
    ),

    # SISTRA-05 · Notificación de cargue UP – Director
	path(
    'verificar/propuesta/',
    verificacion_propuesta.lista,
    name='verificacion_propuesta_lista',
),
path(
    'verificar/propuesta/<int:id_propuesta>/',
    verificacion_propuesta.detalle,
    name='verificacion_propuesta_detalle',
),
path(
    'verificar/propuesta/<int:id_propuesta>/decidir/',
    verificacion_propuesta.decidir,
    name='verificacion_propuesta_decidir',
),
path(
    'verificar/propuesta/<int:id_propuesta>/corregir/',
    verificacion_propuesta.corregir,
    name='verificacion_propuesta_corregir',
),
    # SISTRA-08 · Notificación de cargue UP (informe)
    path('informe/', aviso_informe.inicio, name='aviso_informe'),
    path('informe/confirmar/', aviso_informe.confirmar, name='aviso_informe_confirmar'),
    path('informe/ir-up/', aviso_informe.ir_a_up, name='aviso_informe_ir_up'),
    path('informe/descargar/', aviso_informe.descargar, name='aviso_informe_descargar'),

    # SISTRA-09 · Notificación de cargue UP – Director (informe)
    path(
        'verificar/informe/',
        verificacion_informe.lista,
        name='verificacion_informe_lista',
    ),
    path(
        'verificar/informe/<int:id_informe>/',
        verificacion_informe.detalle,
        name='verificacion_informe_detalle',
    ),
    path(
        'verificar/informe/<int:id_informe>/decidir/',
        verificacion_informe.decidir,
        name='verificacion_informe_decidir',
    ),
    path(
        'verificar/informe/<int:id_informe>/corregir/',
        verificacion_informe.corregir,
        name='verificacion_informe_corregir',
    ),
]
