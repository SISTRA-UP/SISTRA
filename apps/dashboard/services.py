"""Consultas, métricas, semáforo y auditoría del dashboard (SISTRA-14)."""

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.parametrizacion.models import (
    Actividad,
    Carrera,
    EstadoPeriodo,
    Parametro,
    PeriodoAcademico,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoActividad, ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado

Usuario = get_user_model()

CLAVE_SEMAFORO_VERDE = 'SEMAFORO_DIAS_VERDE'
CLAVE_SEMAFORO_AMARILLO = 'SEMAFORO_DIAS_AMARILLO'
DIAS_VERDE_POR_DEFECTO = 3
DIAS_AMARILLO_POR_DEFECTO = 7

BADGES_ESTADO_TRAMITE = {
    EstadoTramite.BORRADOR: 'secondary',
    EstadoTramite.EN_REVISION: 'primary',
    EstadoTramite.REQUIERE_MODIFICACION: 'warning',
    EstadoTramite.RECHAZADO: 'danger',
    EstadoTramite.APROBADO: 'success',
    EstadoTramite.SUBIDO_EN_UP: 'info',
    EstadoTramite.APROBADO_EN_UP: 'success',
}


def url_segura(nombre_ruta, *args):
    """Resuelve una URL nombrada sin romper la vista si la ruta aún no existe."""
    try:
        return reverse(nombre_ruta, args=args)
    except NoReverseMatch:
        return None


def registrar_auditoria_dashboard(usuario, panel):
    """Registra el ingreso al dashboard en la tabla `auditoria`."""
    Auditoria.objects.create(
        usuario=usuario,
        accion='CONSULTA_DASHBOARD',
        tabla_afectada='dashboard',
        id_registro_afectado=usuario.pk,
        detalle=f'Acceso al panel principal ({panel})',
        resultado='EXITO',
    )


def obtener_umbrales_semaforo():
    """Lee los días límite del semáforo desde `parametro` con valores de respaldo."""
    parametros = dict(
        Parametro.objects.filter(
            clave__in=[CLAVE_SEMAFORO_VERDE, CLAVE_SEMAFORO_AMARILLO]
        ).values_list('clave', 'valor')
    )
    try:
        dias_verde = int(parametros.get(CLAVE_SEMAFORO_VERDE, DIAS_VERDE_POR_DEFECTO))
    except (TypeError, ValueError):
        dias_verde = DIAS_VERDE_POR_DEFECTO

    try:
        dias_amarillo = int(
            parametros.get(CLAVE_SEMAFORO_AMARILLO, DIAS_AMARILLO_POR_DEFECTO)
        )
    except (TypeError, ValueError):
        dias_amarillo = DIAS_AMARILLO_POR_DEFECTO

    return dias_verde, max(dias_amarillo, dias_verde + 1)


def evaluar_semaforo(fecha_envio, estado, umbrales=None):
    """Calcula el nivel del semáforo para trámites pendientes de revisión."""
    if estado != EstadoTramite.EN_REVISION or not fecha_envio:
        return {'nivel': None, 'etiqueta': 'No aplica', 'color': 'light', 'dias': None}

    dias_verde, dias_amarillo = umbrales or obtener_umbrales_semaforo()
    dias = max((timezone.now() - fecha_envio).days, 0)

    if dias <= dias_verde:
        return {
            'nivel': 'verde',
            'etiqueta': f'{dias} d · Al día',
            'color': 'success',
            'dias': dias,
        }
    if dias <= dias_amarillo:
        return {
            'nivel': 'amarillo',
            'etiqueta': f'{dias} d · Por vencer',
            'color': 'warning',
            'dias': dias,
        }
    return {
        'nivel': 'rojo',
        'etiqueta': f'{dias} d · Atrasado',
        'color': 'danger',
        'dias': dias,
    }


def _notificaciones_no_leidas(usuario, limite=10):
    return list(
        Notificacion.objects.filter(usuario=usuario, fecha_lectura__isnull=True)
        .select_related('propuesta', 'informe')
        .order_by('-fecha_creacion')[:limite]
    )


def _periodo_vigente():
    return PeriodoAcademico.objects.filter(estado=EstadoPeriodo.VIGENTE).first()


def _calcular_avance_estudiante(proceso, propuesta_activa, informe_activo):
    """Calcula el porcentaje de avance (0% en FA-01 si aún no existe propuesta)."""
    if not proceso or not propuesta_activa:
        return 0, []

    etapas = list(
        ProcesoActividad.objects.filter(proceso=proceso)
        .select_related('actividad')
        .order_by('actividad__orden')
    )
    if etapas:
        total = len(etapas)
        completadas = sum(
            1 for etapa in etapas if etapa.estado == EstadoAvance.FINALIZADA
        )
        porcentaje = round((completadas / total) * 100)
        return porcentaje, etapas

    # Cálculo de respaldo basado en los hitos de propuesta e informe si aún no hay etapas sembradas
    catalogo = list(
        Actividad.objects.filter(estado=Estado.ACTIVO).order_by('orden')
    )
    hitos = [
        propuesta_activa.estado != EstadoTramite.BORRADOR,
        propuesta_activa.estado
        in (
            EstadoTramite.APROBADO,
            EstadoTramite.SUBIDO_EN_UP,
            EstadoTramite.APROBADO_EN_UP,
        ),
        propuesta_activa.estado == EstadoTramite.APROBADO_EN_UP,
        informe_activo is not None
        and informe_activo.estado != EstadoTramite.BORRADOR,
        informe_activo is not None
        and informe_activo.estado
        in (
            EstadoTramite.APROBADO,
            EstadoTramite.SUBIDO_EN_UP,
            EstadoTramite.APROBADO_EN_UP,
        ),
        informe_activo is not None
        and informe_activo.estado == EstadoTramite.APROBADO_EN_UP,
    ]
    porcentaje = round((sum(1 for h in hitos if h) / len(hitos)) * 100)
    return porcentaje, catalogo


def construir_contexto_estudiante(usuario, id_carrera=None):
    """Construye el contexto de consulta para el panel «Mi Trabajo Social»."""
    estudiante = Estudiante.objects.filter(usuario=usuario).first()
    inscripciones = []
    inscripcion_actual = None

    if estudiante:
        inscripciones = list(
            EstudianteCarrera.objects.filter(estudiante=estudiante)
            .select_related('carrera__facultad')
            .order_by('-estado', 'carrera__nombre')
        )
        activas = [
            ins for ins in inscripciones if ins.estado == EstadoInscripcion.ACTIVO
        ]
        pool = activas or inscripciones
        if id_carrera:
            inscripcion_actual = next(
                (ins for ins in pool if str(ins.carrera_id) == str(id_carrera)),
                pool[0] if pool else None,
            )
        elif pool:
            inscripcion_actual = pool[0]

    proceso = None
    propuesta_activa = None
    informe_activo = None
    ultimo_cargue = None
    ultima_observacion = None

    if inscripcion_actual:
        proceso = ProcesoTrabajoSocial.objects.filter(
            estudiante_carrera=inscripcion_actual
        ).first()

    if proceso:
        propuesta_activa = (
            Propuesta.objects.filter(proceso=proceso, archivada=False)
            .exclude(estado=EstadoTramite.RECHAZADO)
            .select_related('periodo_academico')
            .order_by('-fecha_creacion')
            .first()
        )
        if not propuesta_activa:
            propuesta_activa = (
                Propuesta.objects.filter(proceso=proceso, archivada=False)
                .select_related('periodo_academico')
                .order_by('-fecha_creacion')
                .first()
            )

    if propuesta_activa:
        informe_activo = (
            Informe.objects.filter(propuesta=propuesta_activa, archivado=False)
            .exclude(estado=EstadoTramite.RECHAZADO)
            .select_related('periodo_academico')
            .order_by('-fecha_creacion')
            .first()
        )
        if not informe_activo:
            informe_activo = (
                Informe.objects.filter(propuesta=propuesta_activa, archivado=False)
                .select_related('periodo_academico')
                .order_by('-fecha_creacion')
                .first()
            )

        ultimo_cargue = (
            CargueUp.objects.filter(
                Q(propuesta=propuesta_activa)
                | (Q(informe=informe_activo) if informe_activo else Q(pk__isnull=True))
            )
            .order_by('-fecha_declaracion')
            .first()
        )

        ultima_observacion = (
            HistorialEstado.objects.filter(
                Q(propuesta=propuesta_activa)
                | (Q(informe=informe_activo) if informe_activo else Q(pk__isnull=True))
            )
            .exclude(observacion='')
            .select_related('usuario', 'tipo_rechazo')
            .order_by('-fecha_hora')
            .first()
        )

    avance_porcentaje, etapas = _calcular_avance_estudiante(
        proceso, propuesta_activa, informe_activo
    )

    return {
        'titulo_panel': 'Mi Trabajo Social',
        'subtitulo_panel': 'Consulta el estado de tu propuesta, informe y avance del proceso',
        'rol_panel': 'Estudiante',
        'periodo_vigente': _periodo_vigente(),
        'inscripciones': inscripciones,
        'inscripcion_actual': inscripcion_actual,
        'proceso': proceso,
        'propuesta': propuesta_activa,
        'propuesta_badge': BADGES_ESTADO_TRAMITE.get(
            propuesta_activa.estado, 'secondary'
        )
        if propuesta_activa
        else None,
        'informe': informe_activo,
        'informe_badge': BADGES_ESTADO_TRAMITE.get(
            informe_activo.estado, 'secondary'
        )
        if informe_activo
        else None,
        'ultimo_cargue': ultimo_cargue,
        'ultima_observacion': ultima_observacion,
        'avance_porcentaje': avance_porcentaje,
        'etapas': etapas,
        'avisos': _notificaciones_no_leidas(usuario),
        'enlaces': {
            'montar_propuesta': url_segura('propuestas:montaje'),
            'montar_informe': url_segura('informes:montaje'),
            'cargue_up_propuesta': url_segura('cargue_up:cargue_propuesta'),
            'cargue_up_informe': url_segura('cargue_up:cargue_informe'),
        },
    }


def construir_contexto_director(usuario, filtros):
    """Construye el contexto de seguimiento de carrera para el rol Director."""
    director = Director.objects.filter(usuario=usuario).first()
    asignaciones = []
    if director:
        asignaciones = list(
            DirectorCarrera.objects.filter(director=director, activo=True)
            .select_related('carrera__facultad')
            .order_by('carrera__nombre')
        )

    carreras_ids = [asig.carrera_id for asig in asignaciones]
    umbrales = obtener_umbrales_semaforo()

    propuestas_base = Propuesta.objects.filter(
        proceso__estudiante_carrera__carrera_id__in=carreras_ids,
        archivada=False,
    )
    informes_base = Informe.objects.filter(
        propuesta__proceso__estudiante_carrera__carrera_id__in=carreras_ids,
        archivado=False,
    )
    cargues_pendientes = CargueUp.objects.filter(
        Q(propuesta__proceso__estudiante_carrera__carrera_id__in=carreras_ids)
        | Q(
            informe__propuesta__proceso__estudiante_carrera__carrera_id__in=carreras_ids
        ),
        estado_verificacion=EstadoVerificacion.PENDIENTE,
    ).count()

    conteos_propuestas = dict(
        propuestas_base.values_list('estado').annotate(total=Count('id_propuesta'))
    )
    informes_en_revision = informes_base.filter(
        estado=EstadoTramite.EN_REVISION
    ).count()

    # FA-02: todas las tarjetas inician en 0 si aún no hay registros en la carrera
    tarjetas = [
        {
            'etiqueta': 'Propuestas en revisión',
            'valor': conteos_propuestas.get(EstadoTramite.EN_REVISION, 0),
            'color': 'primary',
        },
        {
            'etiqueta': 'Requieren modificación',
            'valor': conteos_propuestas.get(EstadoTramite.REQUIERE_MODIFICACION, 0),
            'color': 'warning',
        },
        {
            'etiqueta': 'Propuestas aprobadas',
            'valor': conteos_propuestas.get(EstadoTramite.APROBADO, 0)
            + conteos_propuestas.get(EstadoTramite.APROBADO_EN_UP, 0),
            'color': 'success',
        },
        {
            'etiqueta': 'Propuestas rechazadas',
            'valor': conteos_propuestas.get(EstadoTramite.RECHAZADO, 0),
            'color': 'danger',
        },
        {
            'etiqueta': 'Subido en UP por verificar',
            'valor': cargues_pendientes,
            'color': 'info',
        },
        {
            'etiqueta': 'Informes en revisión',
            'valor': informes_en_revision,
            'color': 'secondary',
        },
    ]

    inscripciones_qs = (
        EstudianteCarrera.objects.filter(
            carrera_id__in=carreras_ids, estado=EstadoInscripcion.ACTIVO
        )
        .select_related('estudiante__usuario', 'carrera', 'proceso')
        .order_by('estudiante__usuario__nombre')
    )

    busqueda = (filtros.get('q') or '').strip()
    estado_filtro = filtros.get('estado') or ''
    semaforo_filtro = filtros.get('semaforo') or ''

    if busqueda:
        inscripciones_qs = inscripciones_qs.filter(
            Q(estudiante__usuario__nombre__icontains=busqueda)
            | Q(estudiante__usuario__cedula__icontains=busqueda)
            | Q(estudiante__usuario__correo_institucional__icontains=busqueda)
            | Q(proceso__propuestas__codigo__icontains=busqueda)
            | Q(proceso__propuestas__informes__codigo__icontains=busqueda)
        ).distinct()

    filas_estudiantes = []
    for ins in inscripciones_qs:
        proceso = getattr(ins, 'proceso', None)
        propuesta = None
        informe = None
        if proceso:
            propuesta = (
                Propuesta.objects.filter(proceso=proceso, archivada=False)
                .order_by('-fecha_creacion')
                .first()
            )
        if propuesta:
            informe = (
                Informe.objects.filter(propuesta=propuesta, archivado=False)
                .order_by('-fecha_creacion')
                .first()
            )

        estado_actual = (
            informe.estado
            if informe
            else (propuesta.estado if propuesta else 'Sin propuesta')
        )
        if estado_filtro and (
            (not propuesta or propuesta.estado != estado_filtro)
            and (not informe or informe.estado != estado_filtro)
        ):
            continue

        # Prioriza el semáforo del trámite que esté actualmente en revisión
        if informe and informe.estado == EstadoTramite.EN_REVISION:
            semaforo = evaluar_semaforo(informe.fecha_envio, informe.estado, umbrales)
        elif propuesta and propuesta.estado == EstadoTramite.EN_REVISION:
            semaforo = evaluar_semaforo(
                propuesta.fecha_envio, propuesta.estado, umbrales
            )
        else:
            semaforo = evaluar_semaforo(None, None, umbrales)

        if semaforo_filtro and semaforo['nivel'] != semaforo_filtro:
            continue

        filas_estudiantes.append(
            {
                'estudiante': ins.estudiante.usuario,
                'carrera': ins.carrera,
                'proceso': proceso,
                'propuesta': propuesta,
                'propuesta_badge': BADGES_ESTADO_TRAMITE.get(
                    propuesta.estado, 'secondary'
                )
                if propuesta
                else 'light',
                'informe': informe,
                'informe_badge': BADGES_ESTADO_TRAMITE.get(
                    informe.estado, 'secondary'
                )
                if informe
                else 'light',
                'estado_actual': estado_actual,
                'semaforo': semaforo,
            }
        )

    return {
        'titulo_panel': 'Mis estudiantes',
        'subtitulo_panel': 'Seguimiento por carrera, estados de revisión y tiempos de respuesta',
        'rol_panel': 'Director',
        'periodo_vigente': _periodo_vigente(),
        'asignaciones': asignaciones,
        'tarjetas': tarjetas,
        'filas_estudiantes': filas_estudiantes,
        'avisos': _notificaciones_no_leidas(usuario),
        'enlaces': {
            'aprobacion_propuestas': url_segura('propuestas:aprobacion'),
            'aprobacion_informes': url_segura('informes:aprobacion'),
            'verificacion_propuesta': url_segura('cargue_up:verificacion_propuesta'),
            'verificacion_informe': url_segura('cargue_up:verificacion_informe'),
            'registrar_estudiantes': url_segura('personas:estudiantes'),
        },
    }


def construir_contexto_administrador(usuario, filtros):
    """Construye el contexto institucional global para el rol Administrador (ADMO)."""
    facultad = filtros.get('facultad')
    carrera = filtros.get('carrera')
    periodo = filtros.get('periodo')
    rol = filtros.get('rol')
    busqueda = (filtros.get('q') or '').strip()

    propuestas_qs = Propuesta.objects.filter(archivada=False)
    informes_qs = Informe.objects.filter(archivado=False)
    inscripciones_qs = EstudianteCarrera.objects.filter(estado=EstadoInscripcion.ACTIVO)
    carreras_qs = Carrera.objects.filter(estado=Estado.ACTIVO).select_related('facultad')

    if facultad:
        propuestas_qs = propuestas_qs.filter(
            proceso__estudiante_carrera__carrera__facultad=facultad
        )
        informes_qs = informes_qs.filter(
            propuesta__proceso__estudiante_carrera__carrera__facultad=facultad
        )
        inscripciones_qs = inscripciones_qs.filter(carrera__facultad=facultad)
        carreras_qs = carreras_qs.filter(facultad=facultad)

    if carrera:
        propuestas_qs = propuestas_qs.filter(
            proceso__estudiante_carrera__carrera=carrera
        )
        informes_qs = informes_qs.filter(
            propuesta__proceso__estudiante_carrera__carrera=carrera
        )
        inscripciones_qs = inscripciones_qs.filter(carrera=carrera)
        carreras_qs = carreras_qs.filter(pk=carrera.pk)

    if periodo:
        propuestas_qs = propuestas_qs.filter(periodo_academico=periodo)
        informes_qs = informes_qs.filter(periodo_academico=periodo)

    conteos_propuestas = dict(
        propuestas_qs.values_list('estado').annotate(total=Count('id_propuesta'))
    )
    conteos_informes = dict(
        informes_qs.values_list('estado').annotate(total=Count('id_informe'))
    )

    tarjetas = [
        {
            'etiqueta': 'Estudiantes activos',
            'valor': inscripciones_qs.count(),
            'color': 'dark',
        },
        {
            'etiqueta': 'Propuestas en revisión',
            'valor': conteos_propuestas.get(EstadoTramite.EN_REVISION, 0),
            'color': 'primary',
        },
        {
            'etiqueta': 'Propuestas aprobadas (total)',
            'valor': conteos_propuestas.get(EstadoTramite.APROBADO, 0)
            + conteos_propuestas.get(EstadoTramite.APROBADO_EN_UP, 0),
            'color': 'success',
        },
        {
            'etiqueta': 'Informes en revisión',
            'valor': conteos_informes.get(EstadoTramite.EN_REVISION, 0),
            'color': 'info',
        },
        {
            'etiqueta': 'Informes aprobados en UP',
            'valor': conteos_informes.get(EstadoTramite.APROBADO_EN_UP, 0),
            'color': 'success',
        },
        {
            'etiqueta': 'Trámites rechazados',
            'valor': conteos_propuestas.get(EstadoTramite.RECHAZADO, 0)
            + conteos_informes.get(EstadoTramite.RECHAZADO, 0),
            'color': 'danger',
        },
    ]

    resumen_carreras = []
    for item_carrera in carreras_qs.order_by('facultad__nombre', 'nombre'):
        director_activo = (
            DirectorCarrera.objects.filter(carrera=item_carrera, activo=True)
            .select_related('director__usuario')
            .first()
        )
        resumen_carreras.append(
            {
                'carrera': item_carrera,
                'director': director_activo.director.usuario
                if director_activo
                else None,
                'estudiantes_activos': EstudianteCarrera.objects.filter(
                    carrera=item_carrera, estado=EstadoInscripcion.ACTIVO
                ).count(),
                'propuestas_activas': Propuesta.objects.filter(
                    proceso__estudiante_carrera__carrera=item_carrera,
                    archivada=False,
                )
                .exclude(estado=EstadoTramite.RECHAZADO)
                .count(),
                'informes_activos': Informe.objects.filter(
                    propuesta__proceso__estudiante_carrera__carrera=item_carrera,
                    archivado=False,
                )
                .exclude(estado=EstadoTramite.RECHAZADO)
                .count(),
            }
        )

    usuarios_qs = Usuario.objects.select_related('rol').order_by('nombre')
    if rol:
        usuarios_qs = usuarios_qs.filter(rol=rol)
    if busqueda:
        usuarios_qs = usuarios_qs.filter(
            Q(nombre__icontains=busqueda)
            | Q(cedula__icontains=busqueda)
            | Q(correo_institucional__icontains=busqueda)
            | Q(nombre_usuario__icontains=busqueda)
        )

    return {
        'titulo_panel': 'Administración',
        'subtitulo_panel': 'Panorama institucional de facultades, carreras, procesos y usuarios',
        'rol_panel': 'Administrador',
        'periodo_vigente': _periodo_vigente(),
        'tarjetas': tarjetas,
        'resumen_carreras': resumen_carreras,
        'usuarios_listado': list(usuarios_qs[:25]),
        'total_usuarios_filtrados': usuarios_qs.count(),
        'avisos': _notificaciones_no_leidas(usuario),
        'enlaces': {
            'usuarios': url_segura('usuarios:usuarios'),
            'roles': url_segura('usuarios:roles'),
            'parametrizacion': url_segura('parametrizacion:parametrizacion'),
            'reportes': url_segura('reportes:reportes'),
        },
    }