"""SISTRA-07 · Reactivación masiva de informes."""

import logging

from apps.propuestas.forms.aprobacion import RESULTADO_EXITO
from apps.informes.views.aprobacion_mensajes import (
    MSG_REACTIVACION, MSG_07_05, aviso_decision,
)

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.informes.views.aprobacion_auditoria import auditar_intentos, detalle_transicion
from apps.informes.forms.aprobacion_reactivacion import (
    validar_condiciones_reactivacion,
)
from apps.informes.forms.aprobacion_reactivacion_masiva import (
    ReactivacionMasivaInformeForm,
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
@auditar_intentos("reactivacion_masiva_informe")
def reactivar_masivo(request):
    """Reactiva toda la selección o no modifica ningún informe."""

    permitidos = _informes_del_director(request.user)

    formulario = ReactivacionMasivaInformeForm(
        request.POST,
        informes_permitidos=permitidos,
    )

    if not formulario.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "mensaje": MSG_07_05,
                "errores": formulario.errors.get_json_data(),
            },
            status=400,
        )

    seleccion = list(formulario.cleaned_data["informes"])
    ids = sorted(informe.pk for informe in seleccion)
    propuestas = sorted(
        {informe.propuesta_id for informe in seleccion}
    )

    motivo = formulario.cleaned_data["motivo"]
    versiones = formulario.cleaned_data["versiones"]

    # No se pueden convertir dos informes rechazados de una misma
    # propuesta en activos al mismo tiempo.
    if len(propuestas) != len(ids):
        return _error(
            "Selecciona como máximo un informe por propuesta. "
            "No se modificó ninguno.",
            estado=409,
        )

    try:
        with transaction.atomic():
            # Mismo orden de bloqueo que en la reactivación individual:
            # primero propuestas y después informes.
            list(
                Propuesta.objects.select_for_update()
                .filter(pk__in=propuestas)
                .order_by("pk")
            )

            informes = list(
                permitidos.filter(pk__in=ids)
                .select_for_update(of=("self",))
                .order_by("pk")
            )

            if len(informes) != len(ids):
                return _error(
                    "Algún informe dejó de estar disponible. "
                    "Actualiza la pantalla. No se modificó ninguno.",
                    estado=409,
                )

            # Valida toda la selección antes de guardar.
            for informe in informes:
                if (
                    informe.fecha_actualizacion.isoformat()
                    != versiones[str(informe.pk)]
                ):
                    return _error(
                        f"El informe {informe.codigo} cambió. "
                        "Actualiza la pantalla. No se modificó ninguno.",
                        estado=409,
                    )

                try:
                    validar_condiciones_reactivacion(informe)
                except ValidationError as error:
                    return _error(
                        f"{informe.codigo}: "
                        + " ".join(error.messages)
                        + " No se modificó ningún informe.",
                        estado=409,
                    )

            for informe in informes:
                ahora = timezone.now()
                detalle_auditoria = detalle_transicion(
                    informe, EstadoTramite.EN_REVISION, motivo=motivo, ahora=ahora,
                )
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
                    estado_anterior=EstadoTramite.RECHAZADO,
                    estado_nuevo=EstadoTramite.EN_REVISION,
                    motivo_reactivacion=motivo,
                    tipo_accion="reactivacion_masiva_informe",
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
                    mensaje=aviso_decision(EstadoTramite.EN_REVISION, motivo),
                )

                Auditoria.objects.create(
                    usuario=request.user,
                    accion="reactivacion_masiva_informe",
                    tabla_afectada="informe",
                    id_registro_afectado=informe.pk,
                    detalle=detalle_auditoria,
                    resultado=RESULTADO_EXITO,
                )

    except IntegrityError:
        logger.exception(
            "Conflicto de integridad en la reactivación masiva."
        )

        return _error(
            "Se encontró un conflicto de datos. Comprueba si existe "
            "otro informe activo y actualiza la pantalla. "
            "No se guardaron los cambios de esta operación.",
            estado=409,
        )

    except Exception:
        logger.exception(
            "Error al procesar la reactivación masiva."
        )

        return _error(
            "No fue posible completar la reactivación. "
            "No se guardaron los cambios de esta operación.",
            estado=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "cantidad": len(informes),
            "mensaje": MSG_REACTIVACION,
        }
    )
