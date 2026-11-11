from django.contrib.auth.mixins import PermissionRequiredMixin

PERMISO_PARAMETRIZAR = 'sistema.parametrizar'
PERMISO_CREAR_USUARIOS = 'crear_usuarios'


class ParametrizarRequeridoMixin(PermissionRequiredMixin):
    """Secciones de parametrización: solo el Administrador (RN-11-01, EX-03)."""
    permission_required = PERMISO_PARAMETRIZAR


def contexto_menu(usuario):
    """Qué secciones muestra el menú. El servidor decide el acceso real."""
    return {
        'puede_parametrizar': usuario.has_perm(PERMISO_PARAMETRIZAR),
    }
