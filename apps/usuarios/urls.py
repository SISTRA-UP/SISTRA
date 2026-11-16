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
    path('gestion/nuevo/', roles.crear_usuario, name='usuario_nuevo'),
    path('gestion/<int:id_usuario>/editar/', roles.editar_usuario, name='usuario_editar'),
    path('gestion/<int:id_usuario>/estado/', roles.cambiar_estado_usuario, name='usuario_estado'),
    path('gestion/<int:id_usuario>/eliminar/', roles.eliminar_usuario, name='usuario_eliminar'),

    # SISTRA-13 · Logueo
    path('login/', logueo.login, name='login'),
    path('inicio/', logueo.inicio_estudiante, name='inicio_estudiante'),
    path('inicio/director/', logueo.inicio_director, name='inicio_director'),
    path('inicio/administrador/', logueo.inicio_administrador, name='inicio_administrador'),
    path('cambiar-contrasena/', logueo.cambiar_contrasena, name='cambiar_contrasena'),
    path('recuperar-contrasena/', logueo.recuperar_contrasena, name='recuperar_contrasena'),
    path('logout/', logueo.logout, name='logout'),
]
