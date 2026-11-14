"""SISTRA-07 · Procesamiento de decisiones sobre informes."""

import logging

from apps.propuestas.forms.aprobacion import RESULTADO_EXITO
from apps.informes.views.aprobacion_mensajes import (
    MENSAJES_DECISION, MSG_07_05, MSG_07_06, aviso_decision,
)

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.informes.views.aprobacion_auditoria import auditar_intentos, detalle_transicion
from apps.informes.forms.aprobacion import DecisionInformeForm
from apps.informes.views.aprobacion import _informes_del_director
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import (
    Auditoria,
    HistorialEstado,
    Notificacion,
)


logger = logging.getLogger(__name__)


def _respuesta_error(mensaje, estado=400):
    return JsonResponse(
        {"ok": False, "mensaje": mensaje},
        status=estado,
    )


@login_required
@require_POST
@auditar_intentos("decision_informe")
def decidir(request, id_informe):
    """Procesa una decisión autorizada sobre un informe."""

    # Comprueba permisos y limita la consulta a las carreras del Director.
    informes_permitidos = _informes_del_director(request.user)

    formulario = DecisionInformeForm(request.POST)

    if not formulario.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "mensaje": MSG_07_05,
                "errores": formulario.errors.get_json_data(),
            },
            status=400,
        )

    # La pantalla enviará la fecha de actualización que tenía al abrirse.
    # Permite detectar decisiones simultáneas o confirmaciones repetidas.
    version_vista = request.POST.get(
        "fecha_actualizacion",
        "",
    ).strip()

    if not version_vista:
        return _respuesta_error(
            "Actualiza la pantalla antes de confirmar la decisión."
        )

    justificacion = formulario.cleaned_data["justificacion"]

    nuevo_estado = formulario.cleaned_data["nuevo_estado"]
    observacion = formulario.cleaned_data["observacion"]
    tipo_rechazo = formulario.cleaned_data["tipo_rechazo"]

    try:
        with transaction.atomic():
            # Bloquea el informe mientras se procesa esta decisión.
            # Otra decisión deberá esperar y comprobar la versión de nuevo.
            informe = get_object_or_404(
                informes_permitidos.select_for_update(of=("self",)),
                pk=id_informe,
            )

            if informe.fecha_actualizacion.isoformat() != version_vista:
                return _respuesta_error(
                    "El informe cambió desde que abriste la pantalla. "
                    "Actualiza el listado antes de decidir nuevamente.",
                    estado=409,
                )

            estado_anterior = informe.estado

            estados_permitidos = (
                EstadoTramite.EN_REVISION,
                EstadoTramite.APROBADO,
            )

            if estado_anterior not in estados_permitidos:
                return _respuesta_error(
                    "Solo puedes decidir sobre un informe En revisión "
                    "o corregir una aprobación permitida.",
                    estado=409,
                )

            if estado_anterior == nuevo_estado:
                return _respuesta_error(
                    "El informe ya tiene ese estado.",
                    estado=409,
                )

            if estado_anterior == EstadoTramite.APROBADO:
                if informe.cargues_up.exists():
                    return _respuesta_error(
                        MSG_07_06,
                        estado=409,
                    )

                if not justificacion:
                    return _respuesta_error(
                        MSG_07_05
                    )

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
                tipo_accion="decision_informe",
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
                accion="decision_informe",
                tabla_afectada="informe",
                id_registro_afectado=informe.pk,
                detalle=detalle_auditoria,
                resultado=RESULTADO_EXITO,
            )

            fecha_actualizacion = informe.fecha_actualizacion.isoformat()

    except Exception as error:
        # Conserva las respuestas normales de Django para un informe
        # inexistente o ajeno al Director.
        from django.http import Http404

        if isinstance(error, Http404):
            raise

        logger.exception(
            "Error al guardar la decisión del informe %s.",
            id_informe,
        )

        return _respuesta_error(
            "No fue posible guardar la decisión. "
            "Actualiza la pantalla y vuelve a intentarlo.",
            estado=500,
        )

    return JsonResponse(
        {
            "ok": True,
            "mensaje": MENSAJES_DECISION[nuevo_estado],
            "estado": nuevo_estado,
            "fecha_actualizacion": fecha_actualizacion,
        }
    )
