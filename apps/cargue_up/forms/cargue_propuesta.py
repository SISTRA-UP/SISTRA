"""SISTRA-03 · Cargue en la Plataforma UP: constantes y auditoría.

Requerimiento de negocio BR-03 (SISTRA-03).
Define los mensajes oficiales y el helper de auditoría transversal.
"""

from django.utils import timezone
from apps.seguimiento.models import Auditoria


# ==============================================================================
# MENSAJES OFICIALES DEL BRD (CÓDIGOS MSG-03-XX)
# ==============================================================================
MSG_03_01 = (
    "Tu proyecto aún no ha sido aprobado por tu docente. Podrás cargarlo en la plataforma "
    "de la UP cuando su estado sea Aprobado."
)
MSG_03_02 = (
    "Tu docente no aprobó tu proyecto, por lo que aún no puedes cargarlo en la UP. "
    "Consulta la respuesta de tu docente."
)
MSG_03_03 = (
    "Tu proyecto fue aprobado. Descárgalo y cárgalo en la plataforma de la UP. Mientras no "
    "se registre el cargue, recibirás recordatorios periódicos dentro de la plataforma."
)
MSG_03_04 = (
    "El documento de la propuesta no se encuentra disponible actualmente para su descarga."
)
MSG_03_05 = (
    "El enlace a la plataforma de la Universidad de Pamplona no está disponible actualmente."
)
MSG_03_06 = (
    "Tu proyecto fue rechazado en la UP. Por favor revisa las observaciones del Director, "
    "corrige los puntos señalados y vuelve a radicarlo."
)
MSG_03_07 = (
    "Recordatorio semanal: Tu propuesta fue aprobada. Recuerda radicarla en la Plataforma UP "
    "para continuar con tu proceso de horas sociales."
)
MSG_03_08 = (
    "No tienes proyectos vigentes registrados."
)
MSG_03_09 = (
    "No tienes permiso para acceder a este módulo."
)


def registrar_auditoria(
    usuario,
    accion: str,
    tabla_afectada: str = "propuesta",
    id_registro: int | None = None,
    detalle: str = "",
    resultado: str = "Éxito",
) -> None:
    """Registra eventos de auditoría obligatorios para BR-03.
    
    Usa el vocabulario estandarizado de SISTRA:
    - Resultados: 'Éxito', 'Fallo', 'Bloqueado'.
    - Acciones escritas como frase ('Descargar propuesta', 'Ir a la Plataforma UP', etc.).
    """
    try:
        Auditoria.objects.create(
            usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
            accion=accion[:100],
            tabla_afectada=tabla_afectada[:80],
            id_registro_afectado=id_registro,
            detalle=detalle,
            resultado=resultado[:30],
            fecha_hora=timezone.now(),
        )
    except Exception:
        pass
