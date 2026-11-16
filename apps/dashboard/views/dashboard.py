"""SISTRA-14 · Dashboard: vistas de solo consulta por rol."""

from django.contrib.auth import logout as auth_logout
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache

from apps.dashboard.forms.dashboard import (
    FiltroAdministradorForm,
    FiltroDirectorForm,
)
from apps.dashboard.services import (
    construir_contexto_administrador,
    construir_contexto_director,
    construir_contexto_estudiante,
    registrar_auditoria_dashboard,
)
from apps.personas.models import Director, Estudiante
from apps.usuarios.models import Estado, ROL_ADMINISTRADOR
from apps.usuarios.permisos import requiere_permiso

ROL_ESTUDIANTE = 'Estudiante'
ROL_DIRECTOR = 'Director'

RUTAS_POR_ROL = {
    ROL_ESTUDIANTE: 'dashboard:estudiante',
    ROL_DIRECTOR: 'dashboard:director',
    ROL_ADMINISTRADOR: 'dashboard:administrador',
}


def _resolver_ruta_usuario(usuario):
    """Determina el destino principal según el rol o perfil asociado del usuario."""
    if usuario.rol.nombre in RUTAS_POR_ROL:
        return RUTAS_POR_ROL[usuario.rol.nombre]
    if Estudiante.objects.filter(usuario=usuario).exists():
        return 'dashboard:estudiante'
    if Director.objects.filter(usuario=usuario).exists():
        return 'dashboard:director'
    return 'dashboard:administrador'


def _validar_estado_sesion(request):
    usuario = request.user
    if not usuario.is_active or usuario.rol.estado != Estado.ACTIVO:
        auth_logout(request)
        return redirect('usuarios:login')
    if usuario.requiere_cambio_contrasena:
        return redirect('usuarios:cambiar_contrasena')
    return None


@never_cache
@requiere_permiso('dashboard.ver')
def inicio(request):
    """Punto de entrada raíz `/`: redirige al dashboard del rol autenticado."""
    redireccion = _validar_estado_sesion(request)
    if redireccion:
        return redireccion
    return redirect(_resolver_ruta_usuario(request.user))


@never_cache
@requiere_permiso('dashboard.ver')
def dashboard_estudiante(request):
    redireccion = _validar_estado_sesion(request)
    if redireccion:
        return redireccion

    if _resolver_ruta_usuario(request.user) != 'dashboard:estudiante':
        raise PermissionDenied

    registrar_auditoria_dashboard(request.user, ROL_ESTUDIANTE)
    contexto = construir_contexto_estudiante(
        request.user, id_carrera=request.GET.get('carrera')
    )
    return render(request, 'dashboard/dashboard/inicio.html', contexto)


@never_cache
@requiere_permiso('dashboard.ver')
def dashboard_director(request):
    redireccion = _validar_estado_sesion(request)
    if redireccion:
        return redireccion

    if _resolver_ruta_usuario(request.user) != 'dashboard:director':
        raise PermissionDenied

    form_filtro = FiltroDirectorForm(request.GET or None)
    filtros = form_filtro.cleaned_data if form_filtro.is_valid() else {}

    registrar_auditoria_dashboard(request.user, ROL_DIRECTOR)
    contexto = construir_contexto_director(request.user, filtros)
    contexto['form_filtro'] = form_filtro
    return render(request, 'dashboard/dashboard/inicio.html', contexto)


@never_cache
@requiere_permiso('dashboard.ver')
def dashboard_administrador(request):
    redireccion = _validar_estado_sesion(request)
    if redireccion:
        return redireccion

    if _resolver_ruta_usuario(request.user) != 'dashboard:administrador':
        raise PermissionDenied

    form_filtro = FiltroAdministradorForm(request.GET or None)
    filtros = form_filtro.cleaned_data if form_filtro.is_valid() else {}

    registrar_auditoria_dashboard(request.user, ROL_ADMINISTRADOR)
    contexto = construir_contexto_administrador(request.user, filtros)
    contexto['form_filtro'] = form_filtro
    return render(request, 'dashboard/dashboard/inicio.html', contexto)