"""Rutas de la app usuarios.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', roles.inicio, name='roles'),

En las plantillas se enlazan con el nombre de la app:
{% url 'usuarios:roles' %}.
"""

from django.urls import path  # noqa: F401

from .views import roles  # noqa: F401  SISTRA-10
from .views import logueo  # noqa: F401  SISTRA-13

app_name = 'usuarios'

urlpatterns = [
    # SISTRA-10 · Roles (roles, permisos y usuarios)

    # SISTRA-13 · Logueo
]
