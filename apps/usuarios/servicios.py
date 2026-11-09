"""Creación de usuarios de SISTRA. La carga masiva reutiliza estas funciones.

La contraseña temporal solo existe en memoria: se guarda como hash y se envía
por correo cuando la transacción termina bien. Nunca se devuelve ni se registra.
"""
import logging
import re
import secrets
import unicodedata

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.parametrizacion.models import Carrera
from apps.personas.models import (
    Director, DirectorCarrera, EstadoInscripcion, Estudiante, EstudianteCarrera,
)
from apps.seguimiento.models import Auditoria

from .models import ROL_DIRECTOR, ROL_ESTUDIANTE, Estado, Rol

logger = logging.getLogger(__name__)

ROLES_CREABLES = (ROL_ESTUDIANTE, ROL_DIRECTOR)
_PERFIL_POR_ROL = {ROL_ESTUDIANTE: Estudiante, ROL_DIRECTOR: Director}
CODIGO_CARRERA = '52382'  # Derecho (código SNIES)

_MAYUSCULAS = 'ABCDEFGHJKLMNPQRSTUVWXYZ'   # sin I ni O
_MINUSCULAS = 'abcdefghijkmnpqrstuvwxyz'   # sin l ni o
_DIGITOS = '23456789'                      # sin 0 ni 1
_TELEFONO = re.compile(r'\+?\d{7,15}')

_MENSAJES_DUPLICADO = {
    'cedula': 'Ya existe un usuario con esa cédula.',
    'correo_institucional': 'Ya existe un usuario con ese correo.',
    'nombre_usuario': 'No se pudo generar un nombre de usuario único.',
}


class ErrorCreacion(Exception):
    """Error de negocio con un mensaje apto para mostrar al usuario."""

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def sin_tildes(texto):
    descompuesto = unicodedata.normalize('NFD', texto or '')
    return ''.join(c for c in descompuesto if unicodedata.category(c) != 'Mn').casefold().strip()


def normalizar_cedula(valor):
    return re.sub(r'[\s.]', '', valor or '')


def generar_contrasena_temporal(longitud=12):
    todos = _MAYUSCULAS + _MINUSCULAS + _DIGITOS
    while True:
        clave = ''.join(secrets.choice(todos) for _ in range(longitud))
        if (
            any(c in _MAYUSCULAS for c in clave)
            and any(c in _MINUSCULAS for c in clave)
            and any(c in _DIGITOS for c in clave)
        ):
            return clave


def derivar_nombre_usuario(correo):
    """`ana.perez@x.co` -> `ana.perez`; si existe, `ana.perez2`, `ana.perez3`..."""
    Usuario = get_user_model()
    base = re.sub(r'[^a-z0-9._-]', '', correo.split('@')[0].lower())[:70] or 'usuario'
    candidato, n = base, 1
    while Usuario.objects.filter(nombre_usuario__iexact=candidato).exists():
        n += 1
        candidato = f'{base}{n}'
    return candidato


def resolver_carrera(texto):
    """Busca una carrera activa por código o por nombre (sin tildes ni mayúsculas)."""
    clave = sin_tildes(texto)
    if not clave:
        raise ErrorCreacion('Indique la carrera.')
    for carrera in Carrera.objects.filter(estado='Activo'):
        if clave in (sin_tildes(carrera.codigo), sin_tildes(carrera.nombre)):
            return carrera
    raise ErrorCreacion(f'La carrera «{(texto or "").strip()}» no existe o está inactiva.')


def _carrera_derecho():
    try:
        return Carrera.objects.get(codigo=CODIGO_CARRERA)
    except Carrera.DoesNotExist:
        raise ErrorCreacion('Falta configurar la carrera de Derecho.') from None


def carrera_del_director(usuario):
    """Carrera activa del Director, o None si no tiene ninguna asignada."""
    director = getattr(usuario, 'director', None)
    if director is None:
        return None
    asignacion = (
        DirectorCarrera.objects.select_related('carrera')
        .filter(director=director, activo=True)
        .first()
    )
    return asignacion.carrera if asignacion else None


def _validar_datos(nombre, apellido, cedula, correo, telefono=''):
    Usuario = get_user_model()
    nombre = ' '.join(f'{nombre or ""} {apellido or ""}'.split())
    cedula = normalizar_cedula(cedula)
    correo = Usuario.objects.normalize_email(correo)
    telefono = re.sub(r'[\s().-]', '', telefono or '')

    if not nombre or len(nombre) > 120:
        raise ErrorCreacion('Ingrese el nombre y el apellido (máximo 120 caracteres en total).')
    if not re.fullmatch(r'\d{5,15}', cedula):
        raise ErrorCreacion('La cédula debe tener solo números (entre 5 y 15 dígitos).')
    try:
        validate_email(correo)
    except ValidationError:
        raise ErrorCreacion('Ingrese un correo válido.') from None
    if not re.fullmatch(r'[a-z0-9][a-z0-9._+-]*@[a-z0-9-]+(\.[a-z0-9-]+)+', correo):
        raise ErrorCreacion('Ingrese un correo válido.')
    dominios = [d.lower() for d in getattr(settings, 'DOMINIOS_CORREO_PERMITIDOS', [])]
    if dominios and correo.rsplit('@', 1)[-1] not in dominios:
        raise ErrorCreacion('El correo debe ser institucional.')
    if telefono and not _TELEFONO.fullmatch(telefono):
        raise ErrorCreacion('El teléfono debe tener entre 7 y 15 dígitos.')
    return nombre, cedula, correo, telefono


def _mensaje_de_validacion(error):
    for campo, errores in getattr(error, 'error_dict', {}).items():
        if any(e.code == 'unique' for e in errores):
            return _MENSAJES_DUPLICADO.get(campo, 'Ya existe un registro con esos datos.')
    return ' '.join(error.messages)


def _enviar_contrasena(usuario, contrasena):
    cuerpo = (
        f'Hola {usuario.nombre},\n\n'
        'Se creó su cuenta en SISTRA.\n\n'
        f'Correo de acceso: {usuario.correo_institucional}\n'
        f'Contraseña temporal: {contrasena}\n\n'
        'Al iniciar sesión por primera vez el sistema le pedirá cambiarla.\n'
    )
    try:
        send_mail('Acceso a SISTRA', cuerpo, None, [usuario.correo_institucional])
    except Exception:
        # El usuario ya existe; no se expone la clave en el log.
        logger.exception(
            'No se pudo enviar la contraseña temporal a %s', usuario.correo_institucional
        )


def crear_usuario(
    *, nombre, cedula, correo, rol, apellido='', telefono='',
    carrera=None, creado_por=None, auditar=True,
):
    """Crea el usuario y su perfil. Un Estudiante queda inscrito en la carrera
    (Derecho si no se indica); un Director se crea sin carrera aquí: la
    asignación la hace `crear_director`.

    Lanza `ErrorCreacion` si los datos no son válidos o ya existen. El correo con
    la contraseña temporal sale cuando la transacción termina bien.
    """
    Usuario = get_user_model()
    if rol not in ROLES_CREABLES:
        raise ErrorCreacion('Solo se pueden crear usuarios con rol Estudiante o Director.')
    nombre, cedula, correo, telefono = _validar_datos(nombre, apellido, cedula, correo, telefono)
    if Usuario.objects.filter(correo_institucional__iexact=correo).exists():
        raise ErrorCreacion(_MENSAJES_DUPLICADO['correo_institucional'])
    try:
        rol_obj = Rol.objects.get(nombre=rol, estado=Estado.ACTIVO)
    except Rol.DoesNotExist:
        raise ErrorCreacion(f'El rol «{rol}» no existe o está inactivo.') from None
    if rol == ROL_ESTUDIANTE:
        carrera = carrera or _carrera_derecho()
    else:
        carrera = None

    contrasena = generar_contrasena_temporal()
    try:
        with transaction.atomic():
            usuario = Usuario.objects.create_user(
                correo,
                contrasena,
                nombre=nombre,
                cedula=cedula,
                telefono=telefono,
                nombre_usuario=derivar_nombre_usuario(correo),
                rol=rol_obj,
                requiere_cambio_contrasena=True,
                estado=Estado.ACTIVO,
            )
            perfil = _PERFIL_POR_ROL[rol].objects.create(usuario=usuario)
            if carrera is not None:
                EstudianteCarrera.objects.create(
                    estudiante=perfil, carrera=carrera, estado=EstadoInscripcion.ACTIVO
                )
            if auditar:
                Auditoria.objects.create(
                    usuario=creado_por,
                    accion='Crear usuario',
                    tabla_afectada='usuario',
                    id_registro_afectado=usuario.pk,
                    detalle=f'Rol: {rol}',
                    resultado='Éxito',
                )
    except ValidationError as error:
        raise ErrorCreacion(_mensaje_de_validacion(error)) from error
    except IntegrityError as error:
        raise ErrorCreacion(
            'Ya existe un usuario con esa cédula, correo o nombre de usuario.'
        ) from error

    transaction.on_commit(lambda: _enviar_contrasena(usuario, contrasena))
    return usuario


def crear_director(*, nombre, apellido, cedula, correo, telefono, carrera, creado_por=None):
    """Crea un Director y lo asigna a la carrera. Una carrera solo puede tener
    un director activo; si ya lo tiene, no se crea nada."""
    if carrera is None or carrera.estado != 'Activo':
        raise ErrorCreacion('Seleccione una carrera activa.')
    actual = (
        DirectorCarrera.objects.select_related('director__usuario')
        .filter(carrera=carrera, activo=True)
        .first()
    )
    if actual:
        raise ErrorCreacion(
            f'{carrera.nombre} ya tiene un director activo ({actual.director.usuario.nombre}).'
        )
    try:
        with transaction.atomic():
            usuario = crear_usuario(
                nombre=nombre, apellido=apellido, cedula=cedula, correo=correo,
                telefono=telefono, rol=ROL_DIRECTOR, creado_por=creado_por,
            )
            asignacion = DirectorCarrera.objects.create(
                director=usuario.director, carrera=carrera,
                fecha_inicio=timezone.localdate(), activo=True,
            )
            Auditoria.objects.create(
                usuario=creado_por,
                accion='Asignar director a carrera',
                tabla_afectada='director_carrera',
                id_registro_afectado=asignacion.pk,
                detalle=f'Carrera: {carrera.nombre}',
                resultado='Éxito',
            )
    except IntegrityError as error:
        raise ErrorCreacion('Esa carrera ya tiene un director activo.') from error
    return usuario


def actualizar_estudiante(usuario, *, nombre, apellido, telefono, carrera):
    """Actualiza nombre y teléfono de un estudiante existente y lo inscribe en la
    carrera si falta. Nunca cambia el correo, el rol ni la contraseña.
    Devuelve True si algo cambió."""
    if usuario.rol.nombre != ROL_ESTUDIANTE or not hasattr(usuario, 'estudiante'):
        raise ErrorCreacion('El usuario existente no es un estudiante.')
    nombre, _, _, telefono = _validar_datos(
        nombre, apellido, usuario.cedula, usuario.correo_institucional, telefono
    )
    cambio = False
    with transaction.atomic():
        if usuario.nombre != nombre or (telefono and usuario.telefono != telefono):
            usuario.nombre = nombre
            usuario.telefono = telefono or usuario.telefono
            usuario.save(update_fields=['nombre', 'telefono'])
            cambio = True
        _, inscrito = EstudianteCarrera.objects.get_or_create(
            estudiante=usuario.estudiante,
            carrera=carrera,
            defaults={'estado': EstadoInscripcion.ACTIVO},
        )
    return cambio or inscrito