"""SISTRA-07 · Auditoría de intentos bloqueados y fallidos."""

import logging
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import Http404

from apps.seguimiento.models import Auditoria
from apps.propuestas.forms.aprobacion import RESULTADO_FALLO, RESULTADO_BLOQUEADO
from apps.informes.views.aprobacion_semaforo import tiempo_acumulado_revision


logger = logging.getLogger(__name__)


def _registrar_intento(request, accion, codigo_http, id_informe=None):
    """Registra el resultado sin copiar contraseñas ni datos del formulario."""

    usuario = request.user

    if not usuario.is_authenticated:
        return

    bloqueado = codigo_http in (403, 404, 409)
    resultado = RESULTADO_BLOQUEADO if bloqueado else RESULTADO_FALLO

    descripciones = {
        400: "Solicitud rechazada por datos incompletos o no válidos.",
        403: "Acceso o acción sin autorización.",
        404: "Informe inexistente o fuera del alcance autorizado.",
        409: "Conflicto de versión, estado o condiciones del informe.",
        500: "La operación no pudo completarse por un error interno.",
    }

    detalle = descripciones.get(
        codigo_http,
        "La operación no se completó.",
    )

    try:
        Auditoria.objects.create(
            usuario=usuario,
            accion=f"intento_{accion}",
            tabla_afectada="informe",
            id_registro_afectado=id_informe,
            detalle=f"HTTP {codigo_http}. {detalle}",
            resultado=resultado,
        )
    except Exception:
        # Un fallo al registrar la auditoría no debe ocultar
        # la respuesta original de la operación.
        logger.exception(
            "No fue posible registrar la auditoría de %s.",
            accion,
        )


def auditar_intentos(accion):
    """Audita errores después de finalizar la transacción de la vista."""

    def decorar(vista):
        @wraps(vista)
        def ejecutar(request, *args, **kwargs):
            id_informe = kwargs.get("id_informe")

            try:
                respuesta = vista(request, *args, **kwargs)

            except PermissionDenied:
                _registrar_intento(
                    request,
                    accion,
                    403,
                    id_informe,
                )
                raise

            except Http404:
                _registrar_intento(
                    request,
                    accion,
                    404,
                    id_informe,
                )
                raise

            except Exception:
                _registrar_intento(
                    request,
                    accion,
                    500,
                    id_informe,
                )
                raise

            if respuesta.status_code >= 400:
                _registrar_intento(
                    request,
                    accion,
                    respuesta.status_code,
                    id_informe,
                )

            return respuesta

        return ejecutar

    return decorar


def detalle_transicion(informe, estado_nuevo, tipo_rechazo=None,
                       observacion="", motivo="", justificacion="", ahora=None):
    """Captura los datos del BRD antes de cambiar el estado o fecha de envío."""
    estudiante = informe.propuesta.proceso.estudiante_carrera.estudiante.usuario
    dias = tiempo_acumulado_revision(informe, ahora=ahora).days
    partes = [
        f"Cédula: {estudiante.cedula}",
        f"Estudiante: {estudiante.nombre}",
        f"Días semáforo: {dias}",
        f"Transición: {informe.estado} -> {estado_nuevo}",
        f"Causal: {tipo_rechazo.nombre if tipo_rechazo else 'No aplica'}",
        f"Observación: {observacion or motivo}",
    ]
    if justificacion:
        partes.append(f"Justificación del cambio: {justificacion}")
    return " | ".join(partes)
