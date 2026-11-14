"""SISTRA-03 · Cargue en la Plataforma UP: constantes y auditoría.

Requerimiento de negocio BR-03 (SISTRA-03).
Define los mensajes oficiales (tabla de mensajes del BRD) y el helper de auditoría.
"""

from django.utils import timezone

from apps.seguimiento.models import Auditoria

# ==============================================================================
# MENSAJES OFICIALES DEL BRD (SISTRA-03)
# ==============================================================================
MSG_03_01 = (
    "Tu propuesta fue aprobada. Descárgala y cárgala en la Plataforma UP; "
    "luego vuelve y pulsa Subido en UP."
)
MSG_03_02 = (
    "Se abrió la Plataforma UP en una pestaña nueva. "
    "Cuando termines, vuelve y pulsa Subido en UP."
)
MSG_03_03 = (
    "Tu propuesta está aprobada y aún no has indicado que la subiste a la Plataforma UP."
)
MSG_03_04 = "No pudimos descargar tu propuesta. Inténtalo de nuevo."
MSG_03_05 = "El enlace a la Plataforma UP no está disponible por ahora."
MSG_03_06 = "Podrás cargar tu propuesta en la Plataforma UP cuando sea aprobada."


def registrar_auditoria(
    usuario,
    accion: str,
    tabla_afectada: str = "propuesta",
    id_registro: int | None = None,
    detalle: str = "",
    resultado: str = "Éxito",
) -> None:
    """Registra eventos de auditoría de SISTRA-03.

    La auditoría es obligatoria: si falla al guardar, el error se propaga.
    Vocabulario: resultado 'Éxito', 'Fallo' o 'Bloqueado'; acción como frase.
    """
    Auditoria.objects.create(
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        accion=accion[:100],
        tabla_afectada=tabla_afectada[:80],
        id_registro_afectado=id_registro,
        detalle=detalle,
        resultado=resultado[:30],
        fecha_hora=timezone.now(),
    )
