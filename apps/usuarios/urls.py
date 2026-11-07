"""Rutas de la app usuarios.

En las plantillas se enlazan con el nombre de la app:
{% url 'usuarios:login_estudiante' %}.
"""

from django.urls import path

from .views import logueo, roles

app_name = 'usuarios'

urlpatterns = [
    # SISTRA-10 · Roles (roles, permisos y usuarios)

    # SISTRA-13 · Logueo
    path('login/', logueo.login_estudiante, name='login_estudiante'),
    path('inicio/', logueo.inicio_estudiante, name='inicio_estudiante'),
    path('logout/', logueo.logout_estudiante, name='logout_estudiante'),
]
