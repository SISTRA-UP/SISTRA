"""Consultas y métricas del dashboard docente."""

from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Subquery

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.personas.models import DirectorCarrera, EstadoInscripcion, EstudianteCarrera
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Notificacion


def _propuestas_visibles_en_bandeja(asignacion: DirectorCarrera):
    return (
        Propuesta.objects.filter(
            proceso__estudiante_carrera__carrera=asignacion.carrera,
            archivada=False,
        )
        .exclude(estado=EstadoTramite.BORRADOR)
    )


def _ultimo_estado_cargue(campo: str, *, informe: bool = False):
    relacion = 'informe' if informe else 'propuesta'
    return Subquery(
        CargueUp.objects.filter(**{relacion: OuterRef('pk')})
        .order_by('-fecha_declaracion', '-pk')
        .values(campo)[:1]
    )


def resumen_docente(asignacion: DirectorCarrera) -> dict:
    """Calcula los indicadores del director para su carrera activa."""
    propuestas_en_revision = _propuestas_visibles_en_bandeja(asignacion).filter(
        estado=EstadoTramite.EN_REVISION
    )
    propuestas_con_cargue_pendiente = (
        Propuesta.objects.filter(
            proceso__estudiante_carrera__carrera=asignacion.carrera,
            archivada=False,
            estado=EstadoTramite.SUBIDO_EN_UP,
        )
        .annotate(ultimo_estado_cargue=_ultimo_estado_cargue('estado_verificacion'))
        .filter(ultimo_estado_cargue=EstadoVerificacion.PENDIENTE)
    )
    informes_con_cargue_pendiente = (
        Informe.objects.filter(
            propuesta__proceso__estudiante_carrera__carrera=asignacion.carrera,
            archivado=False,
            estado=EstadoTramite.SUBIDO_EN_UP,
        )
        .annotate(
            ultimo_estado_cargue=_ultimo_estado_cargue('estado_verificacion', informe=True)
        )
        .filter(ultimo_estado_cargue=EstadoVerificacion.PENDIENTE)
    )
    return {
        'asignacion': asignacion,
        'carrera': asignacion.carrera,
        'total_estudiantes': EstudianteCarrera.objects.filter(
            carrera=asignacion.carrera,
            estado=EstadoInscripcion.ACTIVO,
        ).count(),
        'total_propuestas_en_revision': propuestas_en_revision.count(),
        'total_informes_en_revision': Informe.objects.filter(
            propuesta__proceso__estudiante_carrera__carrera=asignacion.carrera,
            archivado=False,
            estado=EstadoTramite.EN_REVISION,
        ).count(),
        'total_propuestas_por_verificar_up': propuestas_con_cargue_pendiente.count(),
        'total_informes_por_verificar_up': informes_con_cargue_pendiente.count(),
    }


def resumen_notificaciones(usuario) -> dict:
    """Devuelve los avisos recientes del usuario y su total sin leer."""
    notificaciones = Notificacion.objects.filter(usuario=usuario)
    return {
        'notificaciones': notificaciones.select_related(
            'propuesta', 'informe'
        ).order_by('-fecha_creacion', '-id_notificacion')[:8],
        'notificaciones_sin_leer': notificaciones.filter(
            fecha_lectura__isnull=True
        ).count(),
    }


def contexto_marco_docente(usuario, vista_dashboard: str) -> dict:
    """Contexto mínimo del marco docente para las pantallas insertadas en él."""
    asignacion = (
        DirectorCarrera.objects.filter(director__usuario=usuario, activo=True)
        .select_related('director', 'carrera')
        .order_by('-fecha_inicio', '-id_director_carrera')
        .first()
    )
    if asignacion is None:
        raise PermissionDenied

    total_propuestas_en_revision = 0
    if usuario.has_perm('propuesta.aprobar'):
        total_propuestas_en_revision = _propuestas_visibles_en_bandeja(asignacion).filter(
            estado=EstadoTramite.EN_REVISION
        ).count()

    return {
        'asignacion': asignacion,
        'vista_dashboard': vista_dashboard,
        'total_propuestas_en_revision': total_propuestas_en_revision,
        **resumen_notificaciones(usuario),
    }
