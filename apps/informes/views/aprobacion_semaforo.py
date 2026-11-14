"""SISTRA-07 · Tiempo de revisión del envío vigente de informes."""

from datetime import timedelta

from django.utils import timezone

from apps.propuestas.forms.aprobacion import obtener_limites_semaforo
from apps.propuestas.models import EstadoTramite


def tiempo_acumulado_revision(informe, ahora=None, historial=None):
    """Tiempo del envío vigente, con el mismo criterio que la propuesta.

    SISTRA-06 actualiza fecha_envio en cada envío o reenvío. Al reactivar
    desde Rechazado, SISTRA-07 desplaza esa fecha para excluir la pausa.
    Los ciclos anteriores a una corrección no se vuelven a sumar.
    No modifica el informe ni su historial.
    """
    if ahora is None:
        ahora = timezone.now()

    fecha_base = (
        informe.fecha_envio
        or getattr(informe, "fecha_actualizacion", None)
        or getattr(informe, "fecha_creacion", None)
    )
    if fecha_base is None:
        return timedelta(0)

    if informe.estado == EstadoTramite.EN_REVISION:
        corte = ahora
    else:
        if historial is None:
            relacion = getattr(informe, "historial", None)
            historial = relacion.all() if relacion is not None else []
        # La última salida detiene el reloj. Una edición posterior del
        # informe no debe sumar días al período ya decidido.
        salidas = [
            evento.fecha_hora
            for evento in historial
            if evento.estado_anterior == EstadoTramite.EN_REVISION
            and evento.estado_nuevo != EstadoTramite.EN_REVISION
            and fecha_base <= evento.fecha_hora <= ahora
        ]
        corte = max(salidas) if salidas else (
            getattr(informe, "fecha_actualizacion", None) or fecha_base
        )
        corte = min(corte, ahora)

    return max(timedelta(0), corte - fecha_base)


def calcular_semaforo_informe(
    informe,
    limites=None,
    ahora=None,
    historial=None,
):
    """Calcula el color del envío vigente; excluye las pausas por rechazo."""

    if ahora is None:
        ahora = timezone.now()

    if historial is None:
        relacion = getattr(informe, "historial", None)
        historial = list(relacion.all()) if relacion is not None else []
    else:
        historial = list(historial)

    tiempo = tiempo_acumulado_revision(
        informe,
        ahora=ahora,
        historial=historial,
    )
    dias = max(0, tiempo.days)

    if informe.estado != EstadoTramite.EN_REVISION:
        return {
            "dias": None,
            "dias_acumulados": dias,
            "color": "detenido",
            "clase": "text-bg-secondary",
            "texto": "Detenido",
            "descripcion": (
                f"Semáforo detenido. {dias} días completos "
                "de revisión del envío vigente."
            ),
        }

    if informe.fecha_envio is None:
        return {
            "dias": None,
            "dias_acumulados": None,
            "color": "sin_fecha",
            "clase": "text-bg-light border text-dark",
            "texto": "Sin fecha",
            "descripcion": (
                "No hay una fecha de envío registrada."
            ),
        }

    if limites is None:
        limites = obtener_limites_semaforo()

    limite_verde, limite_amarillo = limites

    if not 0 <= limite_verde < limite_amarillo:
        limite_verde, limite_amarillo = 7, 14

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
        "dias_acumulados": dias,
        "color": color,
        "clase": clase,
        "texto": f"{dias} días",
        "descripcion": (
            f"{dias} días completos en revisión del envío vigente. "
            f"Semáforo {color}. No incluye el tiempo fuera de revisión."
        ),
    }
