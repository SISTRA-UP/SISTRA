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
    path('roles/', roles.lista_roles, name='roles'),
    path('roles/nuevo/', roles.crear_rol, name='rol_nuevo'),
    path('roles/<int:id_rol>/editar/', roles.editar_rol, name='rol_editar'),
    path('roles/<int:id_rol>/estado/', roles.cambiar_estado_rol, name='rol_estado'),
    path('gestion/', roles.lista_usuarios, name='usuarios'),
    path('gestion/<int:id_usuario>/estado/', roles.cambiar_estado_usuario, name='usuario_estado'),

    # SISTRA-13 · Logueo
]
