from django.contrib.auth.views import LogoutView
from django.urls import path  # noqa: F401

from .views import roles  # noqa: F401  SISTRA-10
from .views import logueo  # noqa: F401  SISTRA-13

app_name = 'usuarios'

urlpatterns = [
    # Cierre de sesión (compartido por todos los módulos)
    path('salir/', LogoutView.as_view(next_page='/'), name='salir'),

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
]
