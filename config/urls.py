"""Rutas raíz del proyecto SISTRA.

El panel administrativo de Django no se expone: el administrador del
sistema tendrá sus propias pantallas (SISTRA-10, 11, 12 y 14).

Cada app de `apps/` registra aquí sus rutas, por ejemplo:

    from django.urls import include, path

    urlpatterns = [
        path('propuestas/', include('apps.propuestas.urls')),
    ]
"""

urlpatterns = []
