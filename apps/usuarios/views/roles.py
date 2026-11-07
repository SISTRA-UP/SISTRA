"""SISTRA-10 · Roles (roles, permisos y usuarios): vistas.

Solo el responsable de este requisito edita este archivo.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import permission_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.usuarios.forms.roles import ROLES_BASE, BusquedaUsuarioForm, RolForm
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()


def _alternar(estado):
    return Estado.INACTIVO if estado == Estado.ACTIVO else Estado.ACTIVO


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
        rol = formulario.save()
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
        formulario.save()
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

    rol.estado = _alternar(rol.estado)
    rol.save(update_fields=['estado'])
    if rol.estado == Estado.INACTIVO:
        messages.success(
            request,
            f'El rol {rol.nombre} quedó inactivo: sus usuarios pierden esos permisos.',
        )
    else:
        messages.success(request, f'El rol {rol.nombre} quedó activo.')
    return redirect('usuarios:roles')


@permission_required('usuario.ver', raise_exception=True)
def lista_usuarios(request):
    formulario = BusquedaUsuarioForm(request.GET or None)
    usuarios = Usuario.objects.select_related('rol').order_by('nombre')

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

    return render(
        request,
        'usuarios/roles/lista_usuarios.html',
        {'formulario': formulario, 'usuarios': usuarios},
    )


@permission_required('usuario.inactivar', raise_exception=True)
@require_POST
def cambiar_estado_usuario(request, id_usuario):
    """Inactiva o reactiva un usuario.

    No hay vista para eliminar: la regla §17 manda desactivar y conservar el
    historial, y las tablas que apuntan a `usuario` usan ON DELETE RESTRICT.
    """
    usuario = get_object_or_404(Usuario, pk=id_usuario)
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes inactivar tu propia cuenta.')
        return redirect('usuarios:usuarios')

    usuario.estado = _alternar(usuario.estado)
    usuario.save(update_fields=['estado'])
    estado = 'inactivo' if usuario.estado == Estado.INACTIVO else 'activo'
    messages.success(request, f'{usuario.nombre} quedó {estado}.')
    return redirect('usuarios:usuarios')
