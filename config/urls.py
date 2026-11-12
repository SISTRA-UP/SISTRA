"""Rutas raíz del proyecto SISTRA.

El panel administrativo de Django no se expone: el administrador del
sistema tendrá sus propias pantallas (SISTRA-10, 11, 12 y 14).

Cada app ya tiene su `urls.py` registrado aquí. Las rutas nuevas se agregan
en el `urls.py` de la app, no en este archivo.
"""

from django.urls import include, path

urlpatterns = [
    path('', include('apps.dashboard.urls')),
    path('usuarios/', include('apps.usuarios.urls')),
    path('parametrizacion/', include('apps.parametrizacion.urls')),
    path('personas/', include('apps.personas.urls')),
    path('propuestas/', include('apps.propuestas.urls')),
    path('informes/', include('apps.informes.urls')),
    path('cargue-up/', include('apps.cargue_up.urls')),
    path('reportes/', include('apps.reportes.urls')),
]
