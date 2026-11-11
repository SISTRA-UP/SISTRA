"""Rutas de la app usuarios.

En las plantillas se enlazan con el nombre de la app:
{% url 'usuarios:login_estudiante' %}.
"""

from django.urls import path

from .views import logueo, roles

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
    path('login/', logueo.login_estudiante, name='login_estudiante'),
    path('inicio/', logueo.inicio_estudiante, name='inicio_estudiante'),
    path('logout/', logueo.logout_estudiante, name='logout_estudiante'),
]
