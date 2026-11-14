"""SISTRA-07 · Mensajes de respuesta y notificación del BRD."""

from apps.propuestas.models import EstadoTramite

MSG_07_01 = "El informe fue aprobado."
MSG_07_02 = "Se pidió la modificación y se avisó al estudiante."
MSG_07_03 = "El informe fue rechazado y se avisó al estudiante."
MSG_REACTIVACION = "El informe fue reactivado y quedó en En revisión."
MSG_07_05 = "Completa los campos obligatorios para continuar."
MSG_07_06 = "No puedes cambiar la decisión: el estudiante ya indicó que subió el informe a la Plataforma UP."

MENSAJES_DECISION = {
    EstadoTramite.APROBADO: MSG_07_01,
    EstadoTramite.REQUIERE_MODIFICACION: MSG_07_02,
    EstadoTramite.RECHAZADO: MSG_07_03,
}


def aviso_decision(estado, observacion):
    """MSG-07-07: solo la observación destinada al estudiante."""
    return f"Tu informe cambió a {estado}. {observacion}".strip()
