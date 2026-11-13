"""Permisos y mixins propios del módulo parametrización."""

from django.contrib.auth.mixins import PermissionRequiredMixin

PERMISO_PARAMETRIZAR = 'sistema.parametrizar'


class ParametrizarRequeridoMixin(PermissionRequiredMixin):
    """Secciones de parametrización: solo el Administrador (RN-11-01, EX-03).

    - Usuario anónimo       → 302 al login (comportamiento estándar de Django).
    - Autenticado sin perm  → 403 Forbidden (raise_exception cuando ya hay sesión).
    """
    permission_required = PERMISO_PARAMETRIZAR

    def handle_no_permission(self):
        # Solo lanzamos excepción (403) si el usuario ya está autenticado.
        # Anónimos siguen recibiendo el redirect al login.
        if self.request.user.is_authenticated:
            self.raise_exception = True
        return super().handle_no_permission()


def contexto_menu(usuario):
    """Qué secciones muestra el menú. El servidor decide el acceso real."""
    return {
        'puede_parametrizar': usuario.has_perm(PERMISO_PARAMETRIZAR),
    }
