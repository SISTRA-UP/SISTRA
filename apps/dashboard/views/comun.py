"""Decoradores compartidos por las vistas de dashboard."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def requiere_rol(nombre_rol: str):
    """Restringe una vista a usuarios autenticados con el rol indicado."""

    def decorador(vista):
        @login_required
        @wraps(vista)
        def protegida(request, *args, **kwargs):
            rol = request.user.rol
            if rol.nombre != nombre_rol or rol.estado != 'Activo':
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        return protegida

    return decorador
