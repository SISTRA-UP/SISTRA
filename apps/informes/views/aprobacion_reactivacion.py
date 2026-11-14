"""SISTRA-07 · Reactivación de informes rechazados."""

import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.informes.views.aprobacion_auditoria import auditar_intentos
from apps.informes.forms.aprobacion_reactivacion import (
    ReactivacionInformeForm,
    validar_condiciones_reactivacion,
)
from apps.informes.views.aprobacion import _informes_del_director
from apps.informes.views.aprobacion_semaforo import tiempo_acumulado_revision
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import (
    Auditoria,
    HistorialEstado,
    Notificacion,
)


logger = logging.getLogger(__name__)


def _error(mensaje, estado=400):
    return JsonResponse(
        {"ok": False, "mensaje": mensaje},
        status=estado,
    )


@login_required
@require_POST
@auditar_intentos("reactivacion_informe")
def reactivar(request, id_informe):
    """Reactiva conservando el tiempo de revisión y excluyendo la pausa."""

    informes_permitidos = _informes_del_director(request.user)

    formulario = ReactivacionInformeForm(request.POST)

    if not formulario.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "mensaje": "Revisa los datos de la reactivación.",
                "errores": formulario.errors.get_json_data(),
            },
            status=400,
        )

    referencia = get_object_or_404(
        informes_permitidos,
        pk=id_informe,
    )

    motivo = formulario.cleaned_data["motivo"]
    version_vista = formulario.cleaned_data["fecha_actualizacion"]

    try:
        with transaction.atomic():
            # Serializa las reactivaciones de informes de una propuesta.
            Propuesta.objects.select_for_update().get(
                pk=referencia.propuesta_id,
            )

            informe = get_object_or_404(
                informes_permitidos.select_for_update(of=("self",)),
                pk=id_informe,
            )

            if informe.fecha_actualizacion != version_vista:
                return _error(
                    "El informe cambió desde que abriste la pantalla. "
                    "Actualiza el listado.",
                    estado=409,
                )

            validar_condiciones_reactivacion(informe)

            estado_anterior = informe.estado

            ahora = timezone.now()
            # Igual que en propuestas: conserva el plazo, no la pausa.
            # No es una nueva entrega; version_entrega no cambia.
            if informe.fecha_envio is not None:
                informe.fecha_envio = ahora - tiempo_acumulado_revision(
                    informe, ahora=ahora,
                )
            informe.estado = EstadoTramite.EN_REVISION
            informe.save(
                update_fields=["estado", "fecha_envio", "fecha_actualizacion"]
            )

            HistorialEstado.objects.create(
                informe=informe,
                usuario=request.user,
                estado_anterior=estado_anterior,
                estado_nuevo=EstadoTramite.EN_REVISION,
                motivo_reactivacion=motivo,
                tipo_accion="reactivacion_informe",
                fecha_hora=ahora,
            )

            estudiante = (
                informe.propuesta.proceso
                .estudiante_carrera.estudiante.usuario
            )

            Notificacion.objects.create(
                usuario=estudiante,
                informe=informe,
                tipo="reactivacion_informe",
                mensaje=(
                    f"Tu informe {informe.codigo} fue reactivado "
                    f"y volvió a En revisión. Motivo: {motivo}"
                ),
            )

            Auditoria.objects.create(
                usuario=request.user,
                accion="reactivacion_informe",
                tabla_afectada="informe",
                id_registro_afectado=informe.pk,
                detalle=(
                    f"Estado anterior: {estado_anterior}. "
                    f"Estado nuevo: {EstadoTramite.EN_REVISION}. "
                    f"Motivo: {motivo}"
                ),
                resultado="Exitoso",
            )

            nueva_version = informe.fecha_actualizacion.isoformat()

    except Http404:
        raise

    except ValidationError as error:
        return _error(
            " ".join(error.messages),
            estado=409,
        )

    except IntegrityError:
        logger.exception(
            "Conflicto de integridad al reactivar el informe %s.",
            id_informe,
        )

        return _error(
            "No se pudo reactivar por un conflicto de datos. "
            "Comprueba si ya existe otro informe activo "
            "y actualiza la pantalla.",
            estado=409,
        )

    except Exception:
        logger.exception(
            "Error al reactivar el informe %s.",
            id_informe,
        )

        return _error(
            "No fue posible completar la reactivación. "
            "No se guardaron los cambios de esta operación.",
            estado=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "mensaje": (
                "El informe volvió a En revisión "
                "y se notificó al estudiante."
            ),
            "estado": EstadoTramite.EN_REVISION,
            "fecha_actualizacion": nueva_version,
        }
    )
