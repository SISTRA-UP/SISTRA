"""SISTRA-13 · Inicio, recuperación y cierre de sesión."""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    get_user_model,
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from apps.personas.models import Director, Estudiante
from apps.seguimiento.models import Auditoria
from apps.usuarios.forms.logueo import (
    CambiarContrasenaForm,
    LoginForm,
    RecuperarContrasenaForm,
)
from apps.usuarios.models import Estado

logger = logging.getLogger(__name__)

ROL_ESTUDIANTE = 'Estudiante'
ROL_DIRECTOR = 'Director'
ROL_ADMINISTRADOR = 'Administrador'  # En el BRD se denomina ADMO.
ROLES_INICIO = {
    ROL_ESTUDIANTE: 'usuarios:inicio_estudiante',
    ROL_DIRECTOR: 'usuarios:inicio_director',
    ROL_ADMINISTRADOR: 'usuarios:inicio_administrador',
}
ERROR_CREDENCIALES = 'Correo o contraseña incorrectos.'
MENSAJE_INACTIVO = 'Tu cuenta está inactiva. Comunícate con el administrador.'
MENSAJE_BLOQUEO = 'Superaste el número de intentos. Intenta más tarde.'
MENSAJE_CAMBIO_INVALIDO = (
    'La nueva contraseña no cumple la política o no coincide con la confirmación.'
)
MENSAJE_RECUPERACION = (
    'Si los datos están registrados, enviamos una contraseña temporal '
    'a tu correo institucional.'
)
MENSAJE_CAMBIO_OK = 'Tu contraseña se cambió correctamente.'
MENSAJE_INGRESO_OK = 'Bienvenido a SISTRA.'
MAX_INTENTOS_FALLIDOS = 5
DURACION_BLOQUEO = timedelta(minutes=15)
CLAVE_NEXT_SESION = 'sistra13_next_seguro'
# Se verifica este hash PBKDF2 cuando el correo no corresponde a una cuenta
# compatible, para no responder más rápido a correos inexistentes o de otros roles.
_HASH_CONTRASENA_RELLENO = make_password(get_random_string(64))


def _tiene_perfil(usuario, rol):
    if rol == ROL_ESTUDIANTE:
        try:
            usuario.estudiante
        except Estudiante.DoesNotExist:
            return False
        return True
    if rol == ROL_DIRECTOR:
        try:
            usuario.director
        except Director.DoesNotExist:
            return False
        return True
    return rol == ROL_ADMINISTRADOR


def _es_cuenta_soportada(usuario):
    return usuario.rol.nombre in ROLES_INICIO and _tiene_perfil(usuario, usuario.rol.nombre)


def _auditar(usuario, accion, resultado, detalle=''):
    """Audita la acción sin guardar contraseñas, tokens ni valores del formulario."""
    Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tabla_afectada='usuario',
        id_registro_afectado=usuario.pk if usuario else None,
        detalle=detalle,
        resultado=resultado,
    )


def _next_seguro(request, destino):
    if destino and url_has_allowed_host_and_scheme(
        url=destino,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return destino
    return None


def _redirigir_al_inicio(request, usuario, destino=None):
    destino = _next_seguro(request, destino)
    if destino:
        return redirect(destino)
    nombre_ruta = ROLES_INICIO.get(usuario.rol.nombre)
    if nombre_ruta:
        return redirect(nombre_ruta)
    auth_logout(request)
    return redirect('usuarios:login')


def _destino_despues_de_login(request, usuario, destino):
    if usuario.requiere_cambio_contrasena:
        destino_seguro = _next_seguro(request, destino)
        if destino_seguro:
            request.session[CLAVE_NEXT_SESION] = destino_seguro
        return redirect('usuarios:cambiar_contrasena')
    return _redirigir_al_inicio(request, usuario, destino)


@never_cache
@sensitive_post_parameters('contrasena')
@require_http_methods(['GET', 'POST'])
def login(request):
    """Autentica los tres roles base; no permite auto-registro."""
    destino_solicitado = request.POST.get('next') or request.GET.get('next')
    if request.user.is_authenticated:
        if request.user.requiere_cambio_contrasena:
            destino_seguro = _next_seguro(request, destino_solicitado)
            if destino_seguro:
                request.session[CLAVE_NEXT_SESION] = destino_seguro
            return redirect('usuarios:cambiar_contrasena')
        return _redirigir_al_inicio(request, request.user, destino_solicitado)

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        Usuario = get_user_model()
        correo = form.cleaned_data['correo']
        contrasena = form.cleaned_data['contrasena']
        ahora = timezone.now()
        usuario = None
        credenciales_validas = False
        cuenta_inactiva_con_clave_correcta = False
        cuenta_bloqueada_con_clave_correcta = False
        bloqueo_nuevo = False

        with transaction.atomic():
            usuario = (
                Usuario.objects.select_related('rol', 'estudiante', 'director')
                .select_for_update(of=('self',))
                .filter(correo_institucional__iexact=correo)
                .first()
            )
            cuenta_soportada = bool(usuario and _es_cuenta_soportada(usuario))
            if cuenta_soportada:
                contrasena_correcta = usuario.check_password(contrasena)
            else:
                check_password(contrasena, _HASH_CONTRASENA_RELLENO)
                contrasena_correcta = False

            if usuario and usuario.bloqueado_hasta:
                if usuario.bloqueado_hasta > ahora:
                    cuenta_bloqueada_con_clave_correcta = bool(
                        cuenta_soportada
                        and usuario.is_active
                        and usuario.rol.estado == Estado.ACTIVO
                        and contrasena_correcta
                    )
                else:
                    usuario.bloqueado_hasta = None
                    usuario.intentos_fallidos = 0
                    usuario.save(update_fields=['bloqueado_hasta', 'intentos_fallidos'])

            cuenta_activa = bool(
                cuenta_soportada
                and usuario.is_active
                and usuario.rol.estado == Estado.ACTIVO
            )
            cuenta_inactiva_con_clave_correcta = bool(
                cuenta_soportada
                and not cuenta_activa
                and contrasena_correcta
            )
            esta_bloqueada = bool(usuario and usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora)
            credenciales_validas = bool(
                cuenta_activa and not esta_bloqueada and contrasena_correcta
            )

            if credenciales_validas:
                usuario.intentos_fallidos = 0
                usuario.bloqueado_hasta = None
                usuario.save(update_fields=['intentos_fallidos', 'bloqueado_hasta'])
            elif cuenta_activa and not esta_bloqueada:
                usuario.intentos_fallidos += 1
                if usuario.intentos_fallidos >= MAX_INTENTOS_FALLIDOS:
                    usuario.intentos_fallidos = 0
                    usuario.bloqueado_hasta = ahora + DURACION_BLOQUEO
                    bloqueo_nuevo = True
                usuario.save(update_fields=['intentos_fallidos', 'bloqueado_hasta'])

        if credenciales_validas:
            auth_login(
                request,
                usuario,
                backend='django.contrib.auth.backends.ModelBackend',
            )
            messages.success(request, MENSAJE_INGRESO_OK)
            _auditar(usuario, 'Iniciar sesión', 'Éxito', 'Autenticación correcta.')
            return _destino_despues_de_login(request, usuario, destino_solicitado)

        _auditar(usuario, 'Iniciar sesión', 'Fallo', 'Credenciales o estado no válidos.')
        if bloqueo_nuevo:
            _auditar(usuario, 'Bloquear cuenta', 'Éxito', 'Bloqueo temporal de 15 minutos.')
        if cuenta_inactiva_con_clave_correcta:
            mensaje = MENSAJE_INACTIVO
        elif cuenta_bloqueada_con_clave_correcta:
            mensaje = MENSAJE_BLOQUEO
        else:
            # Una contraseña incorrecta siempre recibe el mismo texto, incluso
            # después del quinto intento, para no divulgar qué correos existen.
            mensaje = ERROR_CREDENCIALES
        form.add_error(None, mensaje)

    return render(
        request,
        'usuarios/logueo/login.html',
        {'form': form, 'next': _next_seguro(request, destino_solicitado) or ''},
    )


@never_cache
@login_required
def inicio_estudiante(request):
    return _inicio_por_rol(request, ROL_ESTUDIANTE)


@never_cache
@login_required
def inicio_director(request):
    return _inicio_por_rol(request, ROL_DIRECTOR)


@never_cache
@login_required
def inicio_administrador(request):
    return _inicio_por_rol(request, ROL_ADMINISTRADOR)


def _inicio_por_rol(request, rol_esperado):
    usuario = request.user
    if (
        usuario.rol.estado != Estado.ACTIVO
        or not _es_cuenta_soportada(usuario)
        or not usuario.is_active
    ):
        auth_logout(request)
        return redirect('usuarios:login')
    if usuario.requiere_cambio_contrasena:
        return redirect('usuarios:cambiar_contrasena')
    if usuario.rol.nombre != rol_esperado:
        return _redirigir_al_inicio(request, usuario)
    return render(
        request,
        'usuarios/logueo/inicio_rol.html',
        {
            'nombre_rol': rol_esperado,
            'nombre_usuario': usuario.nombre,
            'dashboard_pendiente': True,
        },
    )


@never_cache
@sensitive_post_parameters('contrasena_actual', 'contrasena_nueva', 'confirmar_contrasena')
@require_http_methods(['GET', 'POST'])
@login_required
def cambiar_contrasena(request):
    """Permite cambiar la contraseña temporal antes de entrar al inicio del rol."""
    if request.method == 'POST':
        Usuario = get_user_model()
        with transaction.atomic():
            usuario = Usuario.objects.select_for_update().get(pk=request.user.pk)
            form = CambiarContrasenaForm(request.POST, usuario=usuario)
            if form.is_valid():
                usuario.set_password(form.cleaned_data['contrasena_nueva'])
                usuario.requiere_cambio_contrasena = False
                usuario.intentos_fallidos = 0
                usuario.bloqueado_hasta = None
                usuario.save(
                    update_fields=[
                        'password',
                        'requiere_cambio_contrasena',
                        'intentos_fallidos',
                        'bloqueado_hasta',
                    ]
                )
                update_session_auth_hash(request, usuario)
                _auditar(usuario, 'Cambiar contraseña', 'Éxito', 'Contraseña actualizada.')
            else:
                _auditar(usuario, 'Cambiar contraseña', 'Fallo', 'Validación de cambio fallida.')
                form.add_error(None, MENSAJE_CAMBIO_INVALIDO)

        if form.is_valid():
            messages.success(request, MENSAJE_CAMBIO_OK)
            destino = request.session.pop(CLAVE_NEXT_SESION, None)
            return _redirigir_al_inicio(
                request,
                request.user,
                destino or request.POST.get('next') or request.GET.get('next'),
            )
    else:
        form = CambiarContrasenaForm(usuario=request.user)

    return render(
        request,
        'usuarios/logueo/cambiar_contrasena.html',
        {'form': form, 'next': request.session.get(CLAVE_NEXT_SESION, '')},
    )


@never_cache
@sensitive_post_parameters('correo')
@require_http_methods(['GET', 'POST'])
def recuperar_contrasena(request):
    """Envía una contraseña temporal y no revela si una cuenta está registrada."""
    if request.user.is_authenticated:
        return _destino_despues_de_login(request, request.user, None)

    form = RecuperarContrasenaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        Usuario = get_user_model()
        correo = form.cleaned_data['correo']
        resultado = 'Fallo'
        usuario_auditoria = None

        with transaction.atomic():
            usuario = (
                Usuario.objects.select_related('rol', 'estudiante', 'director')
                .select_for_update(of=('self',))
                .filter(correo_institucional__iexact=correo)
                .first()
            )
            cuenta_soportada = bool(usuario and _es_cuenta_soportada(usuario))
            cuenta_activa = bool(
                cuenta_soportada
                and usuario.is_active
                and usuario.rol.estado == Estado.ACTIVO
            )
            if cuenta_activa:
                usuario_auditoria = usuario
                contrasena_temporal = get_random_string(20)
                usuario.set_password(contrasena_temporal)
                asunto = 'Recuperación de acceso a SISTRA-UP'
                cuerpo = (
                    f'Hola {usuario.nombre},\n\n'
                    'Solicitaste recuperar tu acceso a SISTRA-UP. '
                    f'Tu contraseña temporal es: {contrasena_temporal}\n\n'
                    'Al ingresar, el sistema te pedirá cambiarla por una nueva. '
                    'Si no solicitaste este cambio, comunícate con el administrador.'
                )
                try:
                    enviados = send_mail(
                        asunto,
                        cuerpo,
                        settings.DEFAULT_FROM_EMAIL,
                        [usuario.correo_institucional],
                        fail_silently=False,
                    )
                except Exception:
                    logger.warning(
                        'No se pudo enviar el correo de recuperación a usuario id=%s.',
                        usuario.pk,
                    )
                else:
                    if enviados:
                        usuario.requiere_cambio_contrasena = True
                        usuario.intentos_fallidos = 0
                        usuario.bloqueado_hasta = None
                        usuario.save(
                            update_fields=[
                                'password',
                                'requiere_cambio_contrasena',
                                'intentos_fallidos',
                                'bloqueado_hasta',
                            ]
                        )
                        usuario_auditoria = usuario
                        resultado = 'Éxito'
            else:
                # El camino sin cuenta también realiza una verificación PBKDF2.
                check_password(get_random_string(64), _HASH_CONTRASENA_RELLENO)
                usuario_auditoria = usuario

            _auditar(
                usuario_auditoria,
                'Recuperar contraseña',
                resultado,
                'Solicitud procesada sin exponer el estado de la cuenta.',
            )

        messages.info(request, MENSAJE_RECUPERACION)
        return redirect('usuarios:recuperar_contrasena')

    return render(
        request,
        'usuarios/logueo/recuperar_contrasena.html',
        {'form': form},
    )


@never_cache
@require_POST
@login_required
def logout(request):
    usuario = request.user
    _auditar(usuario, 'Cerrar sesión', 'Éxito', 'Sesión cerrada por el usuario.')
    auth_logout(request)
    return redirect('usuarios:login')
