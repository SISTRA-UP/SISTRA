"""SISTRA-10 · Roles (roles, permisos y usuarios): vistas.

Solo el responsable de este requisito edita este archivo.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import permission_required
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.parametrizacion.models import Carrera
from apps.seguimiento.models import Auditoria
from apps.usuarios.forms.roles import (
    ROLES_BASE,
    BusquedaUsuarioForm,
    RolForm,
    UsuarioForm,
)
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()

RESULTADO_EXITO = 'Éxito'
RESULTADO_FALLO = 'Fallo'


def _alternar(estado):
    return Estado.INACTIVO if estado == Estado.ACTIVO else Estado.ACTIVO


# --- Auditoría (criterio: todo cambio de usuarios, roles y permisos queda registrado) ---


def _auditar(request, accion, tabla, id_registro=None, detalle='', resultado=RESULTADO_EXITO):
    """Deja constancia en `seguimiento.auditoria`.

    `usuario` es **quién hizo** la acción; a quién se le hizo va en
    `id_registro_afectado`, que es una referencia lógica sin clave foránea. Por
    eso auditar a un usuario no impide borrarlo después.
    """
    Auditoria.objects.create(
        usuario=request.user if request.user.is_authenticated else None,
        accion=accion[:100],
        tabla_afectada=tabla[:80],
        id_registro_afectado=id_registro,
        detalle=detalle,
        resultado=resultado[:30],
    )


def _legible(campo, valor):
    """Texto corto de un valor para el detalle de la auditoría."""
    if valor is None or valor == '':
        return '—'
    if campo == 'rol':
        rol = valor if isinstance(valor, Rol) else Rol.objects.filter(pk=valor).first()
        return rol.nombre if rol else str(valor)
    if campo == 'carrera':
        carrera = valor if isinstance(valor, Carrera) else Carrera.objects.filter(pk=valor).first()
        return carrera.nombre if carrera else str(valor)
    return str(valor)


def _detalle_cambios(formulario):
    """"campo: antes → después" de cada campo que cambió, para la auditoría.

    `permisos` y `carrera` se saltan porque no son campos del modelo: no están
    en `formulario.initial`, así que su valor anterior no se podría leer de
    aquí. Los reporta el propio formulario en `permisos_agregados`,
    `permisos_quitados` y `cambio_de_carrera`.
    """
    partes = []
    for campo in formulario.changed_data:
        if campo in ('permisos', 'carrera'):
            continue
        partes.append(
            f'{campo}: {_legible(campo, formulario.initial.get(campo))} → '
            f'{_legible(campo, formulario.cleaned_data.get(campo))}'
        )
    return ' · '.join(partes)


def _detalle_permisos(formulario):
    partes = []
    if formulario.permisos_agregados:
        partes.append('permisos +[' + ', '.join(formulario.permisos_agregados) + ']')
    if formulario.permisos_quitados:
        partes.append('permisos -[' + ', '.join(formulario.permisos_quitados) + ']')
    return ' · '.join(partes)


def _retrato(usuario):
    """Los datos del usuario en texto, para poder auditar un borrado."""
    return (
        f'nombre: {usuario.nombre} · cedula: {usuario.cedula} · '
        f'correo: {usuario.correo_institucional} · rol: {usuario.rol.nombre}'
    )


def _juntar(*partes):
    return ' · '.join(parte for parte in partes if parte)


# --- Roles y permisos ---


def _formulario_de_rol(request, rol=None):
    return RolForm(
        request.POST or None,
        instance=rol,
        puede_asignar_permisos=request.user.has_perm('rol.asignar_permisos'),
    )


@permission_required('rol.ver', raise_exception=True)
def lista_roles(request):
    roles = list(Rol.objects.annotate(total_permisos=Count('asignaciones')).order_by('nombre'))
    for rol in roles:
        rol.es_base = rol.nombre in ROLES_BASE
    return render(request, 'usuarios/roles/lista_roles.html', {'roles': roles})


@permission_required('rol.crear', raise_exception=True)
def crear_rol(request):
    formulario = _formulario_de_rol(request)
    if request.method == 'POST' and formulario.is_valid():
        with transaction.atomic():
            rol = formulario.save()
            _auditar(
                request,
                'Crear rol',
                'rol',
                rol.pk,
                _juntar(f'nombre: {rol.nombre}', _detalle_permisos(formulario)),
            )
        messages.success(request, f'Se creó el rol {rol.nombre}.')
        return redirect('usuarios:roles')
    return render(
        request,
        'usuarios/roles/rol_formulario.html',
        {'formulario': formulario, 'titulo': 'Nuevo rol', 'rol': None},
    )


@permission_required('rol.editar', raise_exception=True)
def editar_rol(request, id_rol):
    rol = get_object_or_404(Rol, pk=id_rol)
    formulario = _formulario_de_rol(request, rol)
    if request.method == 'POST' and formulario.is_valid():
        with transaction.atomic():
            formulario.save()
            detalle = _juntar(
                _detalle_cambios(formulario), _detalle_permisos(formulario)
            )
            if detalle:
                _auditar(request, 'Editar rol', 'rol', rol.pk, detalle)
        messages.success(request, f'Se actualizó el rol {rol.nombre}.')
        return redirect('usuarios:roles')
    return render(
        request,
        'usuarios/roles/rol_formulario.html',
        {'formulario': formulario, 'titulo': f'Rol {rol.nombre}', 'rol': rol},
    )


@permission_required('rol.inactivar', raise_exception=True)
@require_POST
def cambiar_estado_rol(request, id_rol):
    """Inactiva o reactiva un rol. Nunca se borra: se perdería el historial.

    Los tres roles base (§3.6) no se pueden inactivar. Inactivar
    `Administrador` les quitaría los permisos a todos los administradores
    —incluido el de reactivarlo— y dejaría el sistema sin quién administrarlo.
    """
    rol = get_object_or_404(Rol, pk=id_rol)
    if rol.nombre in ROLES_BASE:
        messages.error(
            request,
            f'{rol.nombre} es un rol base del sistema: no se puede inactivar.',
        )
        return redirect('usuarios:roles')

    anterior = rol.estado
    rol.estado = _alternar(rol.estado)
    rol.save(update_fields=['estado'])
    _auditar(
        request,
        'Cambiar estado de rol',
        'rol',
        rol.pk,
        f'estado: {anterior} → {rol.estado}',
    )
    if rol.estado == Estado.INACTIVO:
        messages.success(
            request,
            f'El rol {rol.nombre} quedó inactivo: sus usuarios pierden esos permisos.',
        )
    else:
        messages.success(request, f'El rol {rol.nombre} quedó activo.')
    return redirect('usuarios:roles')


# --- Usuarios ---


def _carreras_de(usuario):
    """Lo que se muestra en la columna Carrera.

    Un estudiante puede estar inscrito en varias (RG-01); de un Director se
    muestra solo su asignación vigente.
    """
    estudiante = getattr(usuario, 'estudiante', None)
    if estudiante is not None:
        return sorted(
            {inscripcion.carrera.nombre for inscripcion in estudiante.inscripciones.all()}
        )
    director = getattr(usuario, 'director', None)
    if director is not None:
        return sorted(
            {
                asignacion.carrera.nombre
                for asignacion in director.asignaciones.all()
                if asignacion.activo
            }
        )
    return []


@permission_required('usuario.ver', raise_exception=True)
def lista_usuarios(request):
    formulario = BusquedaUsuarioForm(request.GET or None)
    usuarios = (
        Usuario.objects.select_related('rol', 'estudiante', 'director')
        .prefetch_related(
            'estudiante__inscripciones__carrera',
            'director__asignaciones__carrera',
        )
        .order_by('nombre')
    )

    if formulario.is_valid():
        texto = formulario.cleaned_data['q'].strip()
        rol = formulario.cleaned_data['rol']
        if texto:
            usuarios = usuarios.filter(
                Q(nombre__icontains=texto)
                | Q(cedula__icontains=texto)
                | Q(nombre_usuario__icontains=texto)
                | Q(correo_institucional__icontains=texto)
                | Q(estudiante__inscripciones__carrera__nombre__icontains=texto)
                | Q(estudiante__inscripciones__carrera__codigo__icontains=texto)
            ).distinct()
        if rol:
            usuarios = usuarios.filter(rol=rol)

    usuarios = list(usuarios)
    for usuario in usuarios:
        usuario.carreras = _carreras_de(usuario)
        # Quien tiene perfil de estudiante o de Director no se puede eliminar
        # nunca, así que no se le ofrece el botón. Sale de lo ya precargado.
        usuario.tiene_perfil = (
            getattr(usuario, 'estudiante', None) is not None
            or getattr(usuario, 'director', None) is not None
        )

    return render(
        request,
        'usuarios/roles/lista_usuarios.html',
        {'formulario': formulario, 'usuarios': usuarios},
    )


def _formulario_de_usuario(request, usuario=None):
    return UsuarioForm(
        request.POST or None,
        instance=usuario,
        es_su_propia_cuenta=usuario is not None and usuario.pk == request.user.pk,
    )


@permission_required('usuario.crear', raise_exception=True)
def crear_usuario(request):
    """Crea un usuario con una contraseña temporal que nadie ve.

    La contraseña se genera aleatoria y el usuario queda con
    `requiere_cambio_contrasena`. Entregársela es el correo de SIS-19 (RG-09) y
    cambiarla en el primer ingreso es SISTRA-13.
    """
    formulario = _formulario_de_usuario(request)
    if request.method == 'POST' and formulario.is_valid():
        # La auditoría va en la misma transacción: un usuario creado sin
        # registro incumpliría el criterio.
        with transaction.atomic():
            usuario = formulario.save()
            _auditar(
                request,
                'Crear usuario',
                'usuario',
                usuario.pk,
                _juntar(_retrato(usuario), formulario.cambio_de_carrera),
            )
        messages.success(
            request,
            f'Se creó a {usuario.nombre}. Entrará con {usuario.correo_institucional} y '
            f'una contraseña temporal que deberá cambiar en su primer ingreso.',
        )
        return redirect('usuarios:usuarios')
    return render(
        request,
        'usuarios/roles/usuario_formulario.html',
        {'formulario': formulario, 'titulo': 'Nuevo usuario', 'usuario_editado': None},
    )


@permission_required('usuario.editar', raise_exception=True)
def editar_usuario(request, id_usuario):
    usuario = get_object_or_404(Usuario, pk=id_usuario)
    formulario = _formulario_de_usuario(request, usuario)
    if request.method == 'POST' and formulario.is_valid():
        cambios = _detalle_cambios(formulario)
        with transaction.atomic():
            formulario.save()
            # `cambio_de_carrera` solo existe después de guardar, e incluye el
            # cierre de una asignación que no venía del formulario.
            detalle = _juntar(cambios, formulario.cambio_de_carrera)
            if detalle:
                _auditar(request, 'Editar usuario', 'usuario', usuario.pk, detalle)
        messages.success(request, f'Se actualizaron los datos de {usuario.nombre}.')
        return redirect('usuarios:usuarios')
    return render(
        request,
        'usuarios/roles/usuario_formulario.html',
        {
            'formulario': formulario,
            'titulo': usuario.nombre,
            'usuario_editado': usuario,
        },
    )


@permission_required('usuario.inactivar', raise_exception=True)
@require_POST
def cambiar_estado_usuario(request, id_usuario):
    """Inactiva o reactiva un usuario.

    Nadie se puede inactivar a sí mismo: el único Administrador se dejaría por
    fuera del sistema.
    """
    usuario = get_object_or_404(Usuario, pk=id_usuario)
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes inactivar tu propia cuenta.')
        return redirect('usuarios:usuarios')

    anterior = usuario.estado
    usuario.estado = _alternar(usuario.estado)
    usuario.save(update_fields=['estado'])
    _auditar(
        request,
        'Cambiar estado de usuario',
        'usuario',
        usuario.pk,
        f'estado: {anterior} → {usuario.estado}',
    )
    estado = 'inactivo' if usuario.estado == Estado.INACTIVO else 'activo'
    messages.success(request, f'{usuario.nombre} quedó {estado}.')
    return redirect('usuarios:usuarios')


@permission_required('usuario.eliminar', raise_exception=True)
@require_POST
def eliminar_usuario(request, id_usuario):
    """Elimina a un usuario **solo si no tiene nada registrado**.

    Quién tiene historial no lo decide una lista escrita a mano: lo decide la
    base. Todo lo que apunta a `usuario` usa `ON DELETE RESTRICT` (regla §17),
    así que el `delete()` levanta `ProtectedError` y aquí se ofrece inactivar.

    Por eso **ningún estudiante y ningún Director se puede eliminar**: su fila
    en `estudiante` o en `director` ya lo protege. Lo único que se elimina es la
    cuenta creada por error, sin perfil ni historial.
    """
    usuario = get_object_or_404(Usuario, pk=id_usuario)
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes eliminar tu propia cuenta.')
        return redirect('usuarios:usuarios')

    nombre, retrato = usuario.nombre, _retrato(usuario)
    try:
        with transaction.atomic():
            usuario.delete()
            _auditar(request, 'Eliminar usuario', 'usuario', id_usuario, retrato)
    except ProtectedError:
        _auditar(
            request,
            'Eliminar usuario',
            'usuario',
            id_usuario,
            retrato,
            RESULTADO_FALLO,
        )
        messages.warning(
            request,
            f'{nombre} tiene información registrada en el sistema y no se puede '
            f'eliminar. Puedes inactivarlo para que no vuelva a entrar.',
        )
        return redirect('usuarios:usuarios')

    messages.success(request, f'Se eliminó a {nombre}.')
    return redirect('usuarios:usuarios')
