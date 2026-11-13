"""SISTRA-07 · Tiempo acumulado de revisión de informes."""

from datetime import timedelta

from django.utils import timezone

from apps.propuestas.forms.aprobacion import obtener_limites_semaforo
from apps.propuestas.models import EstadoTramite


def tiempo_acumulado_revision(informe, ahora=None, historial=None):
    """Suma los intervalos En revisión registrados en el historial.

    No modifica fecha_envio ni ningún registro.
    La fecha de envío sirve como inicio del primer intervalo cuando
    todavía no existe un evento de entrada a revisión.
    """

    if ahora is None:
        ahora = timezone.now()

    if historial is None:
        relacion = getattr(informe, "historial", None)
        historial = relacion.all() if relacion is not None else []

    eventos = sorted(
        (
            evento
            for evento in historial
            if evento.fecha_hora <= ahora
        ),
        key=lambda evento: (
            evento.fecha_hora,
            getattr(evento, "pk", 0) or 0,
        ),
    )

    total = timedelta(0)
    inicio = None
    fecha_envio = informe.fecha_envio

    # Compatibilidad con informes cuyo primer envío no quedó
    # registrado en el historial, como nuestros datos de demostración.
    if fecha_envio is not None and fecha_envio <= ahora:
        if not eventos:
            inicio = fecha_envio
        elif (
            eventos[0].estado_anterior == EstadoTramite.EN_REVISION
            and fecha_envio <= eventos[0].fecha_hora
        ):
            inicio = fecha_envio

    for evento in eventos:
        anterior = evento.estado_anterior
        nuevo = evento.estado_nuevo
        fecha = evento.fecha_hora

        sale_de_revision = (
            anterior == EstadoTramite.EN_REVISION
            and nuevo != EstadoTramite.EN_REVISION
        )

        entra_en_revision = (
            nuevo == EstadoTramite.EN_REVISION
            and anterior != EstadoTramite.EN_REVISION
        )

        if sale_de_revision and inicio is not None:
            if fecha >= inicio:
                total += fecha - inicio
            inicio = None

        elif entra_en_revision and inicio is None:
            inicio = fecha

    if (
        informe.estado == EstadoTramite.EN_REVISION
        and inicio is not None
        and ahora >= inicio
    ):
        total += ahora - inicio

    return total


def calcular_semaforo_informe(
    informe,
    limites=None,
    ahora=None,
    historial=None,
):
    """Calcula el color usando el tiempo acumulado En revisión."""

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
                "de revisión acumulados según el historial disponible."
            ),
        }

    tiene_entrada = any(
        evento.estado_nuevo == EstadoTramite.EN_REVISION
        and evento.fecha_hora <= ahora
        for evento in historial
    )

    if informe.fecha_envio is None and not tiene_entrada:
        return {
            "dias": None,
            "dias_acumulados": None,
            "color": "sin_fecha",
            "clase": "text-bg-light border text-dark",
            "texto": "Sin fecha",
            "descripcion": (
                "No hay una fecha de envío ni una entrada a revisión."
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
            f"{dias} días completos acumulados en revisión. "
            f"Semáforo {color}. No incluye el tiempo fuera de revisión."
        ),
    }