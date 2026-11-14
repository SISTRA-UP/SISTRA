"""SISTRA-04 · Notificación de cargue UP: formularios y validaciones.

Solo el responsable de este requisito edita este archivo.
"""

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from apps.personas.models import DirectorCarrera
from apps.propuestas.models import EstadoTramite, Propuesta

# Permiso del rol Estudiante (BRD Tabla 32); lo siembra cargue_up/0002.
PERMISO_AVISAR = 'cargue_up.avisar'

TIPO_NOTIFICACION_AVISO = 'aviso_cargue_up'
ACCION_AUDITORIA_AVISO = 'aviso_cargue_up'

MSG_04_01 = 'El aviso de cargue en UP se registró y se notificó al director.'
MSG_04_02 = (
    'Solo puedes avisar el cargue en UP cuando la propuesta esté en estado Aprobado.'
)
MSG_04_03 = 'El aviso de cargue en UP ya estaba registrado para esta propuesta.'
MSG_04_04 = 'No hay un director activo asignado a la carrera de la propuesta.'
MSG_04_05 = (
    'No fue posible registrar el aviso de cargue en UP. No se guardaron cambios.'
)
MSG_04_06 = (
    'El cargue de esta propuesta ya fue notificado al director. '
    'No necesitas volver a realizar esta acción'
)


def obtener_propuesta_del_estudiante(
    usuario, id_propuesta: int, *, bloquear: bool = False
) -> Propuesta:
    """Obtiene una propuesta activa que pertenezca estrictamente al estudiante.

    Si la propuesta no existe o es de otro estudiante se responde 404, sin
    revelar datos de trámites ajenos. Con ``bloquear`` se usa
    ``select_for_update`` para serializar confirmaciones simultáneas.
    """
    propuestas = Propuesta.objects.select_related(
        'proceso__estudiante_carrera__estudiante__usuario'
    )
    if bloquear:
        propuestas = propuestas.select_for_update(of=('self',))

    return get_object_or_404(
        propuestas,
        pk=id_propuesta,
        archivada=False,
        proceso__estudiante_carrera__estudiante__usuario=usuario,
    )


def validar_propuesta_aprobada(propuesta: Propuesta) -> None:
    """Comprueba que la propuesta pueda avisarse como Subido en UP."""
    if propuesta.estado != EstadoTramite.APROBADO:
        raise ValidationError(MSG_04_02)


def obtener_director_activo(propuesta: Propuesta) -> DirectorCarrera | None:
    """Devuelve la asignación activa del director de la carrera de la propuesta."""
    carrera = propuesta.proceso.estudiante_carrera.carrera
    return (
        DirectorCarrera.objects.filter(carrera=carrera, activo=True)
        .select_related('director__usuario')
        .first()
    )


def mensaje_notificacion_aviso(propuesta: Propuesta) -> str:
    """Texto interno que recibe el director al declararse el cargue en UP."""
    estudiante = propuesta.proceso.estudiante_carrera.estudiante.usuario
    return (
        f'El estudiante {estudiante.nombre} avisó que subió la propuesta '
        f'{propuesta.codigo} a la Plataforma UP.'
    )
