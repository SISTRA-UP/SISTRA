"""SISTRA-08 · Lógica del aviso «Subido en UP» del informe (BRD v1.2)."""

from django.db import transaction
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.personas.models import DirectorCarrera 
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion

TIPO_NOTIFICACION = 'Subido en UP' 
TIPO_ACCION = 'Subido en UP'
ACCION_AUDITORIA = 'AVISAR_SUBIDO_UP_INFORME'
ACCION_AUDITORIA_BLOQUEADA = 'AVISAR_SUBIDO_UP_INFORME_BLOQUEADO'
RESULTADO_EXITO = 'Éxito'
RESULTADO_BLOQUEADO = 'Bloqueado'

# Estados del informe que habilitan o muestran el cargue (RG-02 / RG-06).
APROBADO = EstadoTramite.APROBADO
SUBIDO_EN_UP = EstadoTramite.SUBIDO_EN_UP        
APROBADO_EN_UP = EstadoTramite.APROBADO_EN_UP

RUTA_ESTUDIANTE = 'propuesta__proceso__estudiante_carrera__estudiante__usuario'

class AvisoInformeError(Exception):
    """Error de negocio; `codigo` apunta al mensaje MSG-08-xx."""

    def __init__(self, codigo):
        super().__init__(codigo)
        self.codigo = codigo


def informe_del_estudiante(usuario):
    """Informe activo del estudiante (no archivado ni rechazado)."""
    return (
        Informe.objects.filter(**{RUTA_ESTUDIANTE: usuario}, archivado=False)
        .exclude(estado=EstadoTramite.RECHAZADO)
        .select_related('propuesta')
        .order_by('-fecha_creacion')
        .first()
    )


def _director_usuario(informe):
    estudiante_carrera = informe.propuesta.proceso.estudiante_carrera  
    asignacion = (
        DirectorCarrera.objects.filter(carrera=estudiante_carrera.carrera, activo=True)
        .select_related('director__usuario')
        .first()
    )
    return asignacion.director.usuario if asignacion else None


def registrar_subido_en_up(usuario, id_informe):
    """Registra que el estudiante cargó el informe en la Plataforma UP.

    Una sola transacción: cargue + cambio de estado + historial + aviso al
    Director + auditoría. Los rechazos se auditan fuera de la transacción.
    """
    try:
        id_informe = int(id_informe)
    except (TypeError, ValueError):
        id_informe = None

    try:
        with transaction.atomic():
            informe = (
                Informe.objects.select_for_update(of=('self',))
                .select_related(RUTA_ESTUDIANTE)
                .filter(pk=id_informe)
                .first()
            )
            if informe is None:
                raise AvisoInformeError('sin_permiso')
            dueno = informe.propuesta.proceso.estudiante_carrera.estudiante.usuario 
            if dueno.pk != usuario.pk:
                raise AvisoInformeError('sin_permiso')           # RN: solo el dueño
            if informe.estado == SUBIDO_EN_UP:
                raise AvisoInformeError('duplicado')             # RN-08-02
            if informe.estado != APROBADO:
                raise AvisoInformeError('no_aprobado')           # RN-08-01

            ahora = timezone.now()
            cargue = CargueUp.objects.create(
                informe=informe,
                fecha_declaracion=ahora,
                estado_verificacion=EstadoVerificacion.PENDIENTE,
            )
            estado_anterior = informe.estado
            informe.estado = SUBIDO_EN_UP
            informe.save(update_fields=['estado', 'fecha_actualizacion'])

            HistorialEstado.objects.create(
                informe=informe,
                usuario=usuario,
                estado_anterior=estado_anterior,
                estado_nuevo=SUBIDO_EN_UP,
                tipo_accion=TIPO_ACCION,
                fecha_hora=ahora,
            )

            director = _director_usuario(informe)
            if director is not None:
                fecha = timezone.localtime(ahora).strftime('%d/%m/%Y')
                Notificacion.objects.create(               # MSG-08-06 → SISTRA-09
                    usuario=director,
                    informe=informe,
                    tipo=TIPO_NOTIFICACION,
                    mensaje=(
                        f'{usuario.nombre} indicó que subió su informe '
                        f'a la Plataforma UP el {fecha}.'
                    ),
                )

            Auditoria.objects.create(
                usuario=usuario,
                accion=ACCION_AUDITORIA,
                tabla_afectada='cargue_up',
                id_registro_afectado=cargue.pk,
                detalle=f'informe={informe.codigo}; director_notificado={director is not None}',
                resultado=RESULTADO_EXITO,
                fecha_hora=ahora,
            )
            return cargue
    except AvisoInformeError as error:
        Auditoria.objects.create(
            usuario=usuario,
            accion=ACCION_AUDITORIA_BLOQUEADA,
            tabla_afectada='informe',
            id_registro_afectado=id_informe,
            detalle=error.codigo,
            resultado=RESULTADO_BLOQUEADO,
        )
        raise