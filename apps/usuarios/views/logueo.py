"""SISTRA-13 · Inicio y cierre de sesión de estudiantes."""

from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.personas.models import Estudiante
from apps.seguimiento.models import Auditoria
from apps.usuarios.forms.logueo import LoginEstudianteForm
from apps.usuarios.models import Estado


ROL_ESTUDIANTE = 'Estudiante'
ERROR_CREDENCIALES = 'Correo o contraseña incorrectos.'


def _es_estudiante_habilitado(usuario):
    """Confirma que la cuenta y el rol están activos y corresponden a estudiante."""
    return (
        usuario.is_active
        and usuario.rol.estado == Estado.ACTIVO
        and usuario.rol.nombre == ROL_ESTUDIANTE
    )


def _tiene_perfil_estudiante(usuario):
    try:
        usuario.estudiante
    except Estudiante.DoesNotExist:
        return False
    return True


def _registrar_intento_login(usuario, resultado):
    """Audita el resultado sin guardar contraseñas ni valores del formulario."""
    Auditoria.objects.create(
        usuario=usuario,
        accion='login_estudiante',
        tabla_afectada='usuario',
        id_registro_afectado=usuario.pk if usuario else None,
        detalle='Intento de inicio de sesión de estudiante.',
        resultado=resultado,
    )


@require_http_methods(['GET', 'POST'])
def login_estudiante(request):
    """Muestra el formulario y crea una sesión solo para estudiantes habilitados."""
    if request.user.is_authenticated:
        return redirect('usuarios:inicio_estudiante')

    form = LoginEstudianteForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        Usuario = get_user_model()
        correo = form.cleaned_data['correo']
        contrasena = form.cleaned_data['contrasena']
        usuario = (
            Usuario.objects.select_related('rol')
            .filter(correo_institucional__iexact=correo)
            .first()
        )

        credenciales_validas = False
        if usuario and _es_estudiante_habilitado(usuario) and _tiene_perfil_estudiante(usuario):
            ahora = timezone.now()
            sigue_bloqueado = bool(usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora)
            if not sigue_bloqueado:
                credenciales_validas = usuario.check_password(contrasena)

        if credenciales_validas:
            # No se conserva ningún contador tras un ingreso correcto. Django
            # actualiza last_login mediante su señal user_logged_in.
            Usuario.objects.filter(pk=usuario.pk).update(
                intentos_fallidos=0,
                bloqueado_hasta=None,
            )
            login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
            _registrar_intento_login(usuario, 'Exitoso')
            return redirect('usuarios:inicio_estudiante')

        if usuario and _es_estudiante_habilitado(usuario) and _tiene_perfil_estudiante(usuario):
            sigue_bloqueado = bool(usuario.bloqueado_hasta and usuario.bloqueado_hasta > timezone.now())
            if not sigue_bloqueado:
                Usuario.objects.filter(pk=usuario.pk).update(
                    intentos_fallidos=F('intentos_fallidos') + 1
                )

        _registrar_intento_login(usuario, 'Fallido')
        # El mismo mensaje cubre correo inexistente, contraseña errada,
        # usuario inactivo, rol inválido y perfil faltante.
        form.add_error(None, ERROR_CREDENCIALES)

    return render(request, 'usuarios/logueo/login.html', {'form': form})


@login_required(login_url='usuarios:login_estudiante')
def inicio_estudiante(request):
    """Página privada temporal hasta que SISTRA-14 implemente el dashboard."""
    if not _es_estudiante_habilitado(request.user) or not _tiene_perfil_estudiante(request.user):
        logout(request)
        return redirect('usuarios:login_estudiante')

    return render(request, 'usuarios/logueo/inicio_estudiante.html')


@require_POST
def logout_estudiante(request):
    """Cierra la sesión por POST para que el formulario quede protegido por CSRF."""
    logout(request)
    return redirect('usuarios:login_estudiante')
