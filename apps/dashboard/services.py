"""Consultas, métricas, semáforo y auditoría del dashboard (SISTRA-14)."""

from django.contrib.auth import get_user_model
from django.db.models import Count, Prefetch, Q
from django.urls import NoReverseMatch, reverse

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.informes.views.aprobacion_semaforo import calcular_semaforo_informe
from apps.parametrizacion.models import (
    Actividad,
    Carrera,
    EstadoPeriodo,
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
from apps.propuestas.forms.aprobacion import (
    RESULTADO_EXITO,
    calcular_semaforo,
    obtener_limites_semaforo,
)
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado

Usuario = get_user_model()

BADGES_ESTADO_TRAMITE = {
    EstadoTramite.BORRADOR: 'secondary',
    EstadoTramite.EN_REVISION: 'primary',
    EstadoTramite.REQUIERE_MODIFICACION: 'warning',
    EstadoTramite.RECHAZADO: 'danger',
    EstadoTramite.APROBADO: 'success',
    EstadoTramite.SUBIDO_EN_UP: 'info',
    EstadoTramite.APROBADO_EN_UP: 'success',
}

ETIQUETAS_SEMAFORO = {
    'verde': ('Al día', 'success'),
    'amarillo': ('Por vencer', 'warning text-dark'),
    'rojo': ('Atrasado', 'danger'),
}


def url_segura(nombre_ruta, *args, defecto='#'):
    """Resuelve una URL nombrada sin romper la vista si la ruta aún no existe."""
    try:
        return reverse(nombre_ruta, args=args)
    except NoReverseMatch:
        return defecto


def solo_disponibles(accesos):
    """Quita los accesos cuyo módulo todavía no tiene ruta, para no mostrar enlaces vacíos."""
    return [acceso for acceso in accesos if acceso['url'] != '#']


def registrar_auditoria_dashboard(usuario, panel):
    """Registra el ingreso al dashboard en la tabla `auditoria`."""
    Auditoria.objects.create(
        usuario=usuario,
        accion='CONSULTA_DASHBOARD',
        tabla_afectada='dashboard',
        id_registro_afectado=usuario.pk,
        detalle=f'Acceso al panel principal ({panel})',
        resultado=RESULTADO_EXITO,
    )


def evaluar_semaforo(propuesta=None, informe=None, limites=None):
    """Mismo semáforo que las bandejas: SISTRA-02 para la propuesta y SISTRA-07 para el informe."""
    if informe is not None and informe.estado == EstadoTramite.EN_REVISION:
        resultado = calcular_semaforo_informe(informe, limites=limites)
    elif propuesta is not None and propuesta.estado == EstadoTramite.EN_REVISION:
        resultado = calcular_semaforo(propuesta, limites=limites)
    else:
        resultado = None
    if not resultado or resultado.get('color') not in ETIQUETAS_SEMAFORO:
        return {'nivel': None, 'etiqueta': 'No aplica', 'color': 'secondary', 'dias': None}
    texto, clase = ETIQUETAS_SEMAFORO[resultado['color']]
    dias = resultado['dias']
    return {'nivel': resultado['color'], 'etiqueta': f'{dias} d · {texto}', 'color': clase, 'dias': dias}


def _notificaciones_no_leidas(usuario, limite=10):
    return list(
        Notificacion.objects.filter(usuario=usuario, fecha_lectura__isnull=True)
        .select_related('propuesta', 'informe')
        .order_by('-fecha_creacion')[:limite]
    )


def _periodo_vigente():
    return PeriodoAcademico.objects.filter(estado=EstadoPeriodo.VIGENTE).first()


def _calcular_avance_estudiante(proceso, propuesta_activa, informe_activo):
    """Calcula el porcentaje de avance y el listado de etapas del proceso."""
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
    """Construye el contexto unificado para el panel «Mi Trabajo Social»."""
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
    notificaciones = _notificaciones_no_leidas(usuario)

    accesos_rapidos = [
        {
            'etiqueta': 'Mi propuesta',
            'descripcion': 'Diligenciar o consultar propuesta de Trabajo Social',
            'url': url_segura('propuestas:montaje'),
            'clase': 'primary',
        },
        {
            'etiqueta': 'Mi informe',
            'descripcion': 'Registrar resultados, conclusiones y recomendaciones',
            'url': url_segura('informes:montaje'),
            'clase': 'outline-primary',
        },
        {
            'etiqueta': 'Cargue en UP',
            'descripcion': 'Declarar subida de propuesta o informe en Plataforma UP',
            'url': url_segura('cargue_up:cargue_propuesta'),
            'clase': 'outline-secondary',
        },
    ]

    return {
        'titulo_panel': 'Mi Trabajo Social',
        'subtitulo_panel': 'Consulta el estado de tu propuesta, informe y avance del proceso',
        'tipo_panel': 'estudiante',
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
        'notificaciones': notificaciones,
        'total_notificaciones': len(notificaciones),
        'accesos_rapidos': solo_disponibles(accesos_rapidos),
    }


def construir_contexto_director(usuario, filtros):
    """Construye el contexto unificado de seguimiento de carrera para el rol Director."""
    director = Director.objects.filter(usuario=usuario).first()
    asignaciones = []
    if director:
        asignaciones = list(
            DirectorCarrera.objects.filter(director=director, activo=True)
            .select_related('carrera__facultad')
            .order_by('carrera__nombre')
        )

    carreras_ids = [asig.carrera_id for asig in asignaciones]
    umbrales = obtener_limites_semaforo()

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

    tarjetas = [
        {
            'titulo': 'Propuestas en revisión',
            'valor': conteos_propuestas.get(EstadoTramite.EN_REVISION, 0),
            'detalle': 'Pendientes de concepto',
            'borde': 'primary',
        },
        {
            'titulo': 'Requieren modificación',
            'valor': conteos_propuestas.get(EstadoTramite.REQUIERE_MODIFICACION, 0),
            'detalle': 'Devueltas a estudiantes',
            'borde': 'warning',
        },
        {
            'titulo': 'Propuestas aprobadas',
            'valor': conteos_propuestas.get(EstadoTramite.APROBADO, 0)
            + conteos_propuestas.get(EstadoTramite.APROBADO_EN_UP, 0),
            'detalle': 'Aprobadas en sistema o UP',
            'borde': 'success',
        },
        {
            'titulo': 'Propuestas rechazadas',
            'valor': conteos_propuestas.get(EstadoTramite.RECHAZADO, 0),
            'detalle': 'No aprobadas en revisión',
            'borde': 'danger',
        },
        {
            'titulo': 'Subido en UP por verificar',
            'valor': cargues_pendientes,
            'detalle': 'Declaraciones pendientes',
            'borde': 'info',
        },
        {
            'titulo': 'Informes en revisión',
            'valor': informes_en_revision,
            'detalle': 'Pendientes de revisión final',
            'borde': 'secondary',
        },
    ]

    inscripciones_qs = (
        EstudianteCarrera.objects.filter(
            carrera_id__in=carreras_ids, estado=EstadoInscripcion.ACTIVO
        )
        .select_related('estudiante__usuario', 'carrera', 'proceso')
        .prefetch_related(
            Prefetch(
                'proceso__etapas',
                queryset=(
                    ProcesoActividad.objects.filter(estado=EstadoAvance.EN_CURSO)
                    .select_related('actividad')
                    .order_by('actividad__orden')
                ),
                to_attr='etapas_en_curso',
            )
        )
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

        etapas_en_curso = getattr(proceso, 'etapas_en_curso', []) if proceso else []
        etapa_actual = (
            etapas_en_curso[0].actividad.nombre if etapas_en_curso else None
        )
        fechas_envio = [
            registro.fecha_envio
            for registro in (propuesta, informe)
            if registro and registro.fecha_envio
        ]
        ultimo_envio = max(fechas_envio, default=None)

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

        semaforo = evaluar_semaforo(propuesta, informe, umbrales)

        if semaforo_filtro and semaforo['nivel'] != semaforo_filtro:
            continue

        filas_estudiantes.append(
            {
                'estudiante': ins.estudiante.usuario,
                'carrera': ins.carrera,
                'proceso': proceso,
                'etapa_actual': etapa_actual,
                'ultimo_envio': ultimo_envio,
                'propuesta': propuesta,
                'propuesta_badge': BADGES_ESTADO_TRAMITE.get(
                    propuesta.estado, 'secondary'
                )
                if propuesta
                else 'secondary',
                'informe': informe,
                'informe_badge': BADGES_ESTADO_TRAMITE.get(
                    informe.estado, 'secondary'
                )
                if informe
                else 'secondary',
                'estado_actual': estado_actual,
                'semaforo': semaforo,
            }
        )

    notificaciones = _notificaciones_no_leidas(usuario)
    accesos_rapidos = [
        {
            'etiqueta': 'Aprobación de propuestas',
            'descripcion': 'Revisar y emitir concepto sobre propuestas',
            'url': url_segura('propuestas:aprobacion'),
            'clase': 'primary',
        },
        {
            'etiqueta': 'Aprobación de informes',
            'descripcion': 'Revisar informes finales enviados',
            'url': url_segura('informes:aprobacion'),
            'clase': 'outline-primary',
        },
        {
            'etiqueta': 'Verificar cargues de propuestas',
            'descripcion': 'Validar cargues de propuestas en Plataforma UP',
            'url': url_segura('cargue_up:verificacion_propuesta'),
            'clase': 'outline-secondary',
        },
        {
            'etiqueta': 'Verificar cargues de informes',
            'descripcion': 'Validar cargues de informes en Plataforma UP',
            'url': url_segura('cargue_up:verificacion_informe_lista'),
            'clase': 'outline-secondary',
        },
        {
            'etiqueta': 'Documentos extra recibidos',
            'descripcion': 'Certificados y evidencias de quienes finalizaron',
            'url': url_segura('cargue_up:documentos_extra_recibidos'),
            'clase': 'outline-secondary',
        },
        {
            'etiqueta': 'Registrar estudiantes',
            'descripcion': 'Inscripción individual o masiva por CSV',
            'url': url_segura('personas:estudiantes'),
            'clase': 'outline-dark',
        },
        {
            'etiqueta': 'Reportes',
            'descripcion': 'Consolidado e indicadores de seguimiento',
            'url': url_segura('reportes:reportes'),
            'clase': 'outline-dark',
        },
    ]

    return {
        'titulo_panel': 'Mis estudiantes',
        'subtitulo_panel': 'Seguimiento por carrera, estados de revisión y tiempos de respuesta',
        'tipo_panel': 'director',
        'periodo_vigente': _periodo_vigente(),
        'asignaciones_director': asignaciones,
        'umbrales': umbrales,
        'tarjetas': tarjetas,
        'filas_estudiantes': filas_estudiantes,
        'notificaciones': notificaciones,
        'total_notificaciones': len(notificaciones),
        'accesos_rapidos': solo_disponibles(accesos_rapidos),
    }


def construir_contexto_administrador(usuario, filtros):
    """Construye el contexto unificado institucional para el rol Administrador."""
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
            'titulo': 'Estudiantes activos',
            'valor': inscripciones_qs.count(),
            'detalle': 'Inscripciones activas en curso',
            'borde': 'dark',
        },
        {
            'titulo': 'Propuestas en revisión',
            'valor': conteos_propuestas.get(EstadoTramite.EN_REVISION, 0),
            'detalle': 'Pendientes de concepto',
            'borde': 'primary',
        },
        {
            'titulo': 'Propuestas aprobadas (total)',
            'valor': conteos_propuestas.get(EstadoTramite.APROBADO, 0)
            + conteos_propuestas.get(EstadoTramite.APROBADO_EN_UP, 0),
            'detalle': 'Aprobadas en sistema o UP',
            'borde': 'success',
        },
        {
            'titulo': 'Informes en revisión',
            'valor': conteos_informes.get(EstadoTramite.EN_REVISION, 0),
            'detalle': 'Pendientes de evaluación',
            'borde': 'info',
        },
        {
            'titulo': 'Informes aprobados en UP',
            'valor': conteos_informes.get(EstadoTramite.APROBADO_EN_UP, 0),
            'detalle': 'Procesos culminados en UP',
            'borde': 'success',
        },
        {
            'titulo': 'Trámites rechazados',
            'valor': conteos_propuestas.get(EstadoTramite.RECHAZADO, 0)
            + conteos_informes.get(EstadoTramite.RECHAZADO, 0),
            'detalle': 'Propuestas e informes rechazados',
            'borde': 'danger',
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

    notificaciones = _notificaciones_no_leidas(usuario)
    accesos_rapidos = [
        {
            'etiqueta': 'Usuarios',
            'descripcion': 'Gestionar cuentas y estados de acceso',
            'url': url_segura('usuarios:usuarios'),
            'clase': 'primary',
        },
        {
            'etiqueta': 'Roles y permisos',
            'descripcion': 'Configurar permisos por rol',
            'url': url_segura('usuarios:roles'),
            'clase': 'outline-primary',
        },
        {
            'etiqueta': 'Parametrización',
            'descripcion': 'Periodos, facultades, carreras y parámetros',
            'url': url_segura('parametrizacion:parametrizacion'),
            'clase': 'outline-secondary',
        },
        {
            'etiqueta': 'Reportes',
            'descripcion': 'Consolidado e indicadores institucionales',
            'url': url_segura('reportes:reportes'),
            'clase': 'outline-dark',
        },
    ]

    return {
        'titulo_panel': 'Administración',
        'subtitulo_panel': 'Panorama institucional de facultades, carreras, procesos y usuarios',
        'tipo_panel': 'administrador',
        'periodo_vigente': _periodo_vigente(),
        'tarjetas': tarjetas,
        'resumen_carreras': resumen_carreras,
        'usuarios_listado': list(usuarios_qs[:25]),
        'total_usuarios_filtrados': usuarios_qs.count(),
        'notificaciones': notificaciones,
        'total_notificaciones': len(notificaciones),
        'accesos_rapidos': solo_disponibles(accesos_rapidos),
    }