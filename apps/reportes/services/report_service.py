
"""SISTRA-12 · Consultas para los reportes de Trabajo Social."""

import re
import unicodedata
from datetime import datetime, time

from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from apps.informes.models import Informe
from apps.personas.models import DirectorCarrera
from apps.propuestas.models import EstadoTramite, Propuesta, SectorEntidad
from apps.seguimiento.models import HistorialEstado


def _fecha_limite(fecha, hora):
    """Convierte una fecha y hora local en un datetime consciente de zona."""
    valor = datetime.combine(fecha, hora)
    return timezone.make_aware(
        valor,
        timezone.get_current_timezone(),
    )


def _normalizar_entidad(nombre):
    """Normaliza espacios y mayúsculas para comparar entidades."""
    nombre = unicodedata.normalize('NFKC', nombre or '')
    return re.sub(r'\s+', ' ', nombre).strip().casefold()


def _fecha_decision(estado):
    """Obtiene la fecha del último historial de un informe para un estado."""
    return HistorialEstado.objects.filter(
        informe=OuterRef('pk'),
        estado_nuevo=estado,
    ).order_by('-fecha_hora').values('fecha_hora')[:1]


def _fecha_decision_propuesta(estado):
    """Obtiene la fecha del último historial de una propuesta para un estado."""
    return HistorialEstado.objects.filter(
        propuesta=OuterRef('pk'),
        estado_nuevo=estado,
    ).order_by('-fecha_hora').values('fecha_hora')[:1]


def _dentro_del_rango(queryset, campo, fecha_desde, fecha_hasta):
    """Filtra por fechas locales, incluyendo el día final completo."""
    if fecha_desde:
        inicio = _fecha_limite(fecha_desde, time.min)
        queryset = queryset.filter(**{
            f'{campo}__gte': inicio,
        })

    if fecha_hasta:
        fin = _fecha_limite(fecha_hasta, time.max)
        queryset = queryset.filter(**{
            f'{campo}__lte': fin,
        })

    return queryset


def _datos_persona(propuesta):
    """Obtiene los datos del estudiante y su carrera desde el proceso."""
    estudiante_carrera = propuesta.proceso.estudiante_carrera
    estudiante = estudiante_carrera.estudiante
    usuario = estudiante.usuario

    return {
        'estudiante_id': estudiante.pk,
        'nombre': usuario.nombre,
        'cedula': usuario.cedula,
        'carrera': estudiante_carrera.carrera.nombre,
    }


def _datos_propuesta(propuesta, fecha_envio=None):
    """Obtiene los campos de la propuesta requeridos por el reporte."""
    return {
        'titulo': propuesta.titulo,
        'entidad': propuesta.entidad,
        'sector_entidad': propuesta.sector_entidad,
        'poblacion_beneficiada': propuesta.poblacion_beneficiada,
        'zona': propuesta.zona,
        'area': propuesta.area,
        'sector': propuesta.sector,
        'unidad': propuesta.unidad,
        'fecha_envio': (
            fecha_envio
            if fecha_envio is not None
            else propuesta.fecha_envio
        ),
    }


def obtener_datos_reporte_trabajo_social(
    user,
    date_start=None,
    date_end=None,
):
    """
    Consulta los registros aprobados y rechazados para el reporte.

    Los usuarios con reporte.descargar_todas consultan todas las carreras.
    Los demás usuarios consultan únicamente sus carreras asignadas.
    """
    puede_ver_todas = user.has_perm('reporte.descargar_todas')

    carreras_permitidas = None

    if not puede_ver_todas:
        carreras_permitidas = list(
            DirectorCarrera.objects.filter(
                director__usuario=user,
                activo=True,
            ).values_list('carrera_id', flat=True)
        )

        if not carreras_permitidas:
            raise PermissionDenied(
                'El director no tiene una asignación activa de carrera.'
            )

    # 1. INFORMES APROBADOS EN LA UNIVERSIDAD

    aprobados_qs = Informe.objects.filter(
        estado=EstadoTramite.APROBADO_EN_UP,
    ).annotate(
        fecha_decision=Subquery(
            _fecha_decision(EstadoTramite.APROBADO_EN_UP)
        ),
    ).filter(
        fecha_decision__isnull=False,
    ).select_related(
        'propuesta__proceso__estudiante_carrera__estudiante__usuario',
        'propuesta__proceso__estudiante_carrera__carrera',
    )

    aprobados_qs = _dentro_del_rango(
        aprobados_qs,
        'fecha_decision',
        date_start,
        date_end,
    )

    if carreras_permitidas is not None:
        aprobados_qs = aprobados_qs.filter(
            propuesta__proceso__estudiante_carrera__carrera_id__in=(
                carreras_permitidas
            )
        )

    aprobados = []

    for informe in aprobados_qs:
        propuesta = informe.propuesta

        registro = {}
        registro.update(_datos_persona(propuesta))
        registro.update(
            _datos_propuesta(
                propuesta,
                fecha_envio=informe.fecha_envio,
            )
        )
        registro.update({
            'estado_final': informe.estado,
            'fecha_decision': informe.fecha_decision,
            'tipo_rechazo': '',
            'observacion': '',
        })

        aprobados.append(registro)

    # 2. PROPUESTAS RECHAZADAS

    propuestas_rechazadas_qs = Propuesta.objects.filter(
        estado=EstadoTramite.RECHAZADO,
    ).annotate(
        fecha_decision=Subquery(
            _fecha_decision_propuesta(EstadoTramite.RECHAZADO)
        ),
    ).filter(
        fecha_decision__isnull=False,
    ).select_related(
        'proceso__estudiante_carrera__estudiante__usuario',
        'proceso__estudiante_carrera__carrera',
    )

    propuestas_rechazadas_qs = _dentro_del_rango(
        propuestas_rechazadas_qs,
        'fecha_decision',
        date_start,
        date_end,
    )

    if carreras_permitidas is not None:
        propuestas_rechazadas_qs = propuestas_rechazadas_qs.filter(
            proceso__estudiante_carrera__carrera_id__in=(
                carreras_permitidas
            )
        )

    rechazados = []

    for propuesta in propuestas_rechazadas_qs:
        historial = HistorialEstado.objects.filter(
            propuesta=propuesta,
            estado_nuevo=EstadoTramite.RECHAZADO,
        ).order_by('-fecha_hora').select_related(
            'tipo_rechazo',
        ).first()

        registro = {}
        registro.update(_datos_persona(propuesta))
        registro.update(_datos_propuesta(propuesta))
        registro.update({
            'estado_final': propuesta.estado,
            'fecha_decision': propuesta.fecha_decision,
            'tipo_rechazo': (
                historial.tipo_rechazo.nombre
                if historial and historial.tipo_rechazo
                else ''
            ),
            'observacion': (
                historial.observacion
                if historial
                else ''
            ),
        })

        rechazados.append(registro)

    # 3. INFORMES RECHAZADOS

    informes_rechazados_qs = Informe.objects.filter(
        estado=EstadoTramite.RECHAZADO,
    ).annotate(
        fecha_decision=Subquery(
            _fecha_decision(EstadoTramite.RECHAZADO)
        ),
    ).filter(
        fecha_decision__isnull=False,
    ).select_related(
        'propuesta__proceso__estudiante_carrera__estudiante__usuario',
        'propuesta__proceso__estudiante_carrera__carrera',
    )

    informes_rechazados_qs = _dentro_del_rango(
        informes_rechazados_qs,
        'fecha_decision',
        date_start,
        date_end,
    )

    if carreras_permitidas is not None:
        informes_rechazados_qs = informes_rechazados_qs.filter(
            propuesta__proceso__estudiante_carrera__carrera_id__in=(
                carreras_permitidas
            )
        )

    for informe in informes_rechazados_qs:
        propuesta = informe.propuesta

        historial = HistorialEstado.objects.filter(
            informe=informe,
            estado_nuevo=EstadoTramite.RECHAZADO,
        ).order_by('-fecha_hora').select_related(
            'tipo_rechazo',
        ).first()

        registro = {}
        registro.update(_datos_persona(propuesta))
        registro.update(
            _datos_propuesta(
                propuesta,
                fecha_envio=informe.fecha_envio,
            )
        )
        registro.update({
            'estado_final': informe.estado,
            'fecha_decision': informe.fecha_decision,
            'tipo_rechazo': (
                historial.tipo_rechazo.nombre
                if historial and historial.tipo_rechazo
                else ''
            ),
            'observacion': (
                historial.observacion
                if historial
                else ''
            ),
        })

        rechazados.append(registro)

    # 4. RESUMEN DE LOS INFORMES APROBADOS

    estudiantes = set()
    entidades_publicas = set()
    entidades_privadas = set()

    for registro in aprobados:
        estudiantes.add(registro['estudiante_id'])

        entidad_normalizada = _normalizar_entidad(
            registro['entidad']
        )

        if not entidad_normalizada:
            continue

        if registro['sector_entidad'] == SectorEntidad.PUBLICO:
            entidades_publicas.add(entidad_normalizada)

        elif registro['sector_entidad'] == SectorEntidad.PRIVADO:
            entidades_privadas.add(entidad_normalizada)

    resumen = {
        'total_estudiantes': len(estudiantes),
        'entidades_publicas': len(entidades_publicas),
        'entidades_privadas': len(entidades_privadas),
        'total_aprobados': len(aprobados),
        'total_rechazados': len(rechazados),
    }

    return {
        'resumen': resumen,
        'aprobados': aprobados,
        'rechazados': rechazados,
        'detalle_finales': aprobados + rechazados,
        'incluir_carrera': puede_ver_todas,
    }
