from django.contrib.auth.mixins import PermissionRequiredMixin

from .models import PERMISO_CREAR_USUARIOS, PERMISO_PARAMETRIZAR


class AccesoParametrizacionMixin(PermissionRequiredMixin):
    """Entrada al módulo: basta con tener alguno de los dos permisos.
    Sin sesión redirige al login; con sesión pero sin permisos, 403."""

    def has_permission(self):
        usuario = self.request.user
        return usuario.has_perm(PERMISO_PARAMETRIZAR) or usuario.has_perm(PERMISO_CREAR_USUARIOS)


class ParametrizarRequeridoMixin(PermissionRequiredMixin):
    """Secciones de parametrización: solo el Administrador."""
    permission_required = PERMISO_PARAMETRIZAR


class CrearUsuariosRequeridoMixin(PermissionRequiredMixin):
    """Creación de estudiantes: solo el Director."""
    permission_required = PERMISO_CREAR_USUARIOS


def contexto_menu(usuario):
    """Qué secciones muestra el menú. El servidor decide el acceso real."""
    return {
        'puede_parametrizar': usuario.has_perm(PERMISO_PARAMETRIZAR),
        'puede_crear_usuarios': usuario.has_perm(PERMISO_CREAR_USUARIOS),
    }