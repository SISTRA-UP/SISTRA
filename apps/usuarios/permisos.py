"""SISTRA-10 · Roles: guardas de acceso y catálogo de opciones del menú.

Las opciones del menú y las guardas de las vistas se deciden por
`permiso.nombre`, nunca por el nombre del rol: el Administrador puede crear
roles nuevos (RG-01) y un menú amarrado a los tres roles base dejaría ciego al
primer rol que creara.
"""

from typing import NamedTuple

from django.contrib.auth.decorators import login_required, permission_required
from django.urls import NoReverseMatch, reverse

# «Inicio» no es administración ni un paso del trámite, y en los mockups va
# suelto arriba, sin rótulo: por eso su grupo no tiene título y el parcial no
# le pinta encabezado.
GRUPO_SIN_ROTULO = ''
GRUPO_ADMINISTRACION = 'Administración'
GRUPO_TRAMITES = 'Trámites'


class Opcion(NamedTuple):
    permiso: str
    ruta: str
    etiqueta: str
    grupo: str


# Cada opción se guarda con el permiso que sembró su propio requisito: no se
# inventan permisos de módulos ajenos ni se decide nada por el nombre del rol.
OPCIONES_DEL_MENU = (
    Opcion('dashboard.ver', 'dashboard:inicio', 'Inicio', GRUPO_SIN_ROTULO),
    Opcion('rol.ver', 'usuarios:roles', 'Roles y permisos', GRUPO_ADMINISTRACION),
    Opcion('usuario.ver', 'usuarios:usuarios', 'Usuarios', GRUPO_ADMINISTRACION),
    Opcion(
        'sistema.parametrizar',
        'parametrizacion:parametrizacion',
        'Parametrización',
        GRUPO_ADMINISTRACION,
    ),
    Opcion('reporte.descargar', 'reportes:reportes', 'Reportes', GRUPO_ADMINISTRACION),
    Opcion(
        'estudiante.registrar',
        'personas:estudiantes',
        'Registrar estudiantes',
        GRUPO_TRAMITES,
    ),
    Opcion(
        'propuesta.aprobar',
        'propuestas:aprobacion',
        'Aprobación de propuestas',
        GRUPO_TRAMITES,
    ),
    Opcion(
        'propuesta.aprobar',
        'cargue_up:verificacion_propuesta',
        'Verificar cargues de propuestas',
        GRUPO_TRAMITES,
    ),
    Opcion('propuesta.montar', 'propuestas:montaje', 'Mi propuesta', GRUPO_TRAMITES),
    Opcion('informe.montar', 'informes:montaje', 'Montar informe', GRUPO_TRAMITES),
    Opcion(
        'informe.aprobar',
        'informes:aprobacion',
        'Aprobación de informes',
        GRUPO_TRAMITES,
    ),
    Opcion(
        'informe.aprobar',
        'cargue_up:verificacion_informe_lista',
        'Verificar cargues de informes',
        GRUPO_TRAMITES,
    ),
    Opcion(
        'informe.aprobar',
        'cargue_up:documentos_extra_recibidos',
        'Documentos extra recibidos',
        GRUPO_TRAMITES,
    ),
    Opcion(
        'cargue_up.avisar',
        'cargue_up:cargue_propuesta',
        'Cargue en la Plataforma UP',
        GRUPO_TRAMITES,
    ),
)

def _grupos_del_catalogo():
    """Los grupos en el orden en que aparecen en el catálogo.

    Se derivan de `OPCIONES_DEL_MENU` y no de una lista aparte: así una opción
    con un grupo nuevo no desaparece del menú en silencio.
    """
    vistos = []
    for opcion in OPCIONES_DEL_MENU:
        if opcion.grupo not in vistos:
            vistos.append(opcion.grupo)
    return vistos


def opciones_visibles(usuario):
    """Las opciones que ese usuario puede ver, agrupadas y listas para pintar.

    Devuelve una lista de grupos; los grupos sin ninguna opción visible no
    aparecen, así que un rol sin permisos de menú no deja títulos huérfanos.
    """
    if usuario is None or not usuario.is_authenticated:
        return []

    grupos = []
    for titulo in _grupos_del_catalogo():
        visibles = []
        for opcion in OPCIONES_DEL_MENU:
            if opcion.grupo != titulo or not usuario.has_perm(opcion.permiso):
                continue
            try:
                direccion = reverse(opcion.ruta)
            except NoReverseMatch:
                # Si otro requisito renombra o retira su ruta, se omite esa
                # opción en vez de tumbar todas las páginas con el menú.
                continue
            visibles.append({'etiqueta': opcion.etiqueta, 'url': direccion})
        if visibles:
            grupos.append({'titulo': titulo, 'opciones': visibles})
    return grupos


def requiere_permiso(permiso):
    """Primero sesión, después permiso.

    `permission_required(..., raise_exception=True)` por sí solo responde 403
    también al anónimo. Apilando `login_required` encima, quien no tiene sesión
    va al login y quien la tiene pero le falta el permiso recibe 403.
    Acepta un permiso o varios, igual que `permission_required`.
    """

    def decorador(vista):
        return login_required(
            permission_required(permiso, raise_exception=True)(vista)
        )

    return decorador
