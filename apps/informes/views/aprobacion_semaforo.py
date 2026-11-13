"""SISTRA-07 · Semáforo de los informes en revisión."""

from django.utils import timezone

from apps.propuestas.forms.aprobacion import obtener_limites_semaforo
from apps.propuestas.models import EstadoTramite


def calcular_semaforo_informe(informe, limites=None, ahora=None):
    """Calcula días completos desde el envío del informe a revisión."""

    if informe.estado != EstadoTramite.EN_REVISION:
        return {
            "dias": None,
            "color": "detenido",
            "clase": "text-bg-secondary",
            "texto": "Detenido",
            "descripcion": "El informe no está en revisión.",
        }

    if informe.fecha_envio is None:
        return {
            "dias": None,
            "color": "sin_fecha",
            "clase": "text-bg-light border text-dark",
            "texto": "Sin fecha",
            "descripcion": "El informe no tiene fecha de envío registrada.",
        }

    if limites is None:
        limites = obtener_limites_semaforo()

    limite_verde, limite_amarillo = limites

    # Evita aplicar una configuración de umbrales incoherente.
    if not 0 <= limite_verde < limite_amarillo:
        limite_verde, limite_amarillo = 7, 14

    if ahora is None:
        ahora = timezone.now()

    dias = max(0, (ahora - informe.fecha_envio).days)

    if dias <= limite_verde:
        color = "verde"
        clase = "text-bg-success"
    elif dias <= limite_amarillo:
        color = "amarillo"
        clase = "text-bg-warning text-dark"
    else:
        color = "rojo"
        clase = "text-bg-danger"

    return {
        "dias": dias,
        "color": color,
        "clase": clase,
        "texto": f"{dias} días",
        "descripcion": f"{dias} días completos en revisión. Semáforo {color}.",
    }