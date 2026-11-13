"""Middlewares de seguridad propios de SISTRA-13."""

from urllib.parse import urlsplit

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class CambioObligatorioContrasenaMiddleware:
    """Impide navegar por SISTRA con una contraseña temporal sin cambiarla."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, 'user', None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and usuario.requiere_cambio_contrasena
        ):
            rutas_permitidas = {
                reverse('usuarios:cambiar_contrasena'),
                reverse('usuarios:logout'),
            }
            ruta_static = urlsplit(settings.STATIC_URL).path.strip('/')
            prefijo_static = f'/{ruta_static}/' if ruta_static else ''
            es_archivo_estatico = bool(
                prefijo_static
                and (
                    request.path_info.startswith(prefijo_static)
                    or request.path_info == prefijo_static.rstrip('/')
                )
            )

            if request.path_info not in rutas_permitidas and not es_archivo_estatico:
                return redirect('usuarios:cambiar_contrasena')

        return self.get_response(request)
