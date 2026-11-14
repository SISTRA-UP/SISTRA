"""SISTRA-07 · Guardado de decisiones masivas."""

import json
import logging

from apps.propuestas.forms.aprobacion import RESULTADO_EXITO
from apps.informes.views.aprobacion_mensajes import (
    MENSAJES_DECISION, MSG_07_05, MSG_07_06, aviso_decision,
)

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.informes.views.aprobacion_auditoria import auditar_intentos, detalle_transicion
from apps.informes.forms.aprobacion_masiva import (
    DecisionMasivaInformeForm,
)
from apps.informes.views.aprobacion import _informes_del_director
from apps.propuestas.models import EstadoTramite
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
@auditar_intentos("decision_masiva_informe")
def decidir_masivo(request):
    """Procesa todos los informes seleccionados o ninguno."""

    informes_permitidos = _informes_del_director(request.user)

    formulario = DecisionMasivaInformeForm(
        request.POST,
        informes_permitidos=informes_permitidos,
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

    ids = sorted(
        formulario.cleaned_data["informes"].values_list(
            "pk",
            flat=True,
        )
    )

    # La pantalla enviará la fecha de actualización de cada informe.
    # Formato: {"id_informe": "fecha ISO", ...}
    try:
        versiones = json.loads(request.POST.get("versiones", ""))
    except (ValueError, TypeError):
        return _error(
            "Actualiza la pantalla antes de confirmar la selección."
        )

    if not isinstance(versiones, dict):
        return _error("Las versiones de los informes no son válidas.")

    if set(versiones) != {str(pk) for pk in ids}:
        return _error(
            "Las versiones no coinciden con los informes seleccionados."
        )

    if not all(isinstance(valor, str) for valor in versiones.values()):
        return _error("Las fechas de los informes no son válidas.")

    nuevo_estado = formulario.cleaned_data["nuevo_estado"]
    observacion = formulario.cleaned_data["observacion"]
    tipo_rechazo = formulario.cleaned_data["tipo_rechazo"]

    justificacion = formulario.cleaned_data["justificacion"]

    try:
        with transaction.atomic():
            # Orden fijo para que operaciones simultáneas bloqueen
            # los informes en el mismo orden.
            informes = list(
                informes_permitidos.filter(pk__in=ids)
                .select_for_update(of=("self",))
                .order_by("pk")
            )

            if len(informes) != len(ids):
                return _error(
                    "Algún informe dejó de estar disponible. "
                    "Actualiza la pantalla.",
                    estado=409,
                )

            # Primero valida toda la selección. Todavía no guarda nada.
            for informe in informes:
                version_actual = informe.fecha_actualizacion.isoformat()

                if versiones[str(informe.pk)] != version_actual:
                    return _error(
                        f"El informe {informe.codigo} cambió. "
                        "Actualiza la pantalla. No se modificó ninguno.",
                        estado=409,
                    )

                if informe.estado not in (
                    EstadoTramite.EN_REVISION,
                    EstadoTramite.APROBADO,
                ):
                    return _error(
                        f"El estado de {informe.codigo} no permite "
                        "esta decisión. No se modificó ningún informe.",
                        estado=409,
                    )

                if informe.estado == nuevo_estado:
                    return _error(
                        f"El informe {informe.codigo} ya tiene "
                        "el estado elegido. No se modificó ninguno.",
                        estado=409,
                    )

                if informe.estado == EstadoTramite.APROBADO:
                    if informe.cargues_up.exists():
                        return _error(
                            MSG_07_06,
                            estado=409,
                        )

                    if not justificacion:
                        return _error(
                            MSG_07_05
                        )

            # Solo guarda si todos los informes superaron la validación.
            for informe in informes:
                estado_anterior = informe.estado
                observacion_guardada = observacion

                if estado_anterior == EstadoTramite.APROBADO:
                    observacion_guardada = (
                        f"Justificación del cambio: {justificacion}\n\n"
                        f"Observación para el estudiante: {observacion}"
                    )

                detalle_auditoria = detalle_transicion(
                    informe, nuevo_estado, tipo_rechazo=tipo_rechazo,
                    observacion=observacion,
                    justificacion=justificacion if estado_anterior == EstadoTramite.APROBADO else "",
                )

                informe.estado = nuevo_estado
                informe.save(
                    update_fields=["estado", "fecha_actualizacion"]
                )

                HistorialEstado.objects.create(
                    informe=informe,
                    usuario=request.user,
                    estado_anterior=estado_anterior,
                    estado_nuevo=nuevo_estado,
                    tipo_rechazo=tipo_rechazo,
                    observacion=observacion_guardada,
                    tipo_accion="decision_masiva_informe",
                )

                estudiante = (
                    informe.propuesta.proceso
                    .estudiante_carrera.estudiante.usuario
                )

                mensaje = aviso_decision(nuevo_estado, observacion)

                Notificacion.objects.create(
                    usuario=estudiante,
                    informe=informe,
                    tipo="decision_informe",
                    mensaje=mensaje,
                )

                Auditoria.objects.create(
                    usuario=request.user,
                    accion="decision_masiva_informe",
                    tabla_afectada="informe",
                    id_registro_afectado=informe.pk,
                    detalle=detalle_auditoria,
                    resultado=RESULTADO_EXITO,
                )

    except Exception:
        logger.exception(
            "Error al guardar una decisión masiva de informes."
        )

        return _error(
            "No fue posible completar la operación. "
            "No se guardaron los cambios de esta selección.",
            estado=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "cantidad": len(informes),
            "mensaje": MENSAJES_DECISION[nuevo_estado],
        }
    )
