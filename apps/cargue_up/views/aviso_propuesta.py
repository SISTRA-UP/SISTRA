"""SISTRA-04 · Notificación de cargue UP: vistas.

Solo el responsable de este requisito edita este archivo.
"""

import logging

from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.forms.aviso_propuesta import (
    ACCION_AUDITORIA_AVISO,
    MSG_04_01,
    MSG_04_02,
    MSG_04_03,
    MSG_04_04,
    MSG_04_05,
    MSG_04_06,
    PERMISO_AVISAR,
    TIPO_NOTIFICACION_AVISO,
    mensaje_notificacion_aviso,
    obtener_director_activo,
    obtener_propuesta_del_estudiante,
)
from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion

logger = logging.getLogger(__name__)


@login_required
@permission_required(PERMISO_AVISAR, raise_exception=True)
@require_GET
def confirmacion(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Muestra la confirmación de «Subido en UP» con el botón habilitado.

    Esta etapa no registra el cargue, no notifica, no audita y no cambia el
    estado de la propuesta. El botón solo se habilita para propuestas en
    estado Aprobado; el POST vuelve a validar el estado antes de guardar.
    """
    propuesta = obtener_propuesta_del_estudiante(request.user, id_propuesta)
    puede_avisar = propuesta.estado == EstadoTramite.APROBADO

    if puede_avisar:
        mensaje_bloqueo = None
    elif propuesta.estado == EstadoTramite.SUBIDO_EN_UP:
        mensaje_bloqueo = MSG_04_06
    else:
        mensaje_bloqueo = MSG_04_02

    return render(
        request,
        'cargue_up/aviso_propuesta/confirmar.html',
        {
            'propuesta': propuesta,
            'puede_avisar': puede_avisar,
            'mensaje_bloqueo': mensaje_bloqueo,
        },
    )


@login_required
@permission_required(PERMISO_AVISAR, raise_exception=True)
@require_POST
def registrar(request: HttpRequest, id_propuesta: int) -> JsonResponse:
    """Registra la confirmación «Subido en UP» de forma atómica e idempotente.

    La propuesta se bloquea mientras se procesa la solicitud. Si otra
    solicitud ya la dejó en Subido en UP, no se crean filas ni avisos nuevos.
    """
    ahora = timezone.now()

    try:
        with transaction.atomic():
            propuesta = obtener_propuesta_del_estudiante(
                request.user, id_propuesta, bloquear=True
            )

            if propuesta.estado == EstadoTramite.SUBIDO_EN_UP:
                return JsonResponse(
                    {
                        'ok': True,
                        'creado': False,
                        'duplicado': True,
                        'mensaje': MSG_04_03,
                        'id_propuesta': propuesta.pk,
                        'estado': propuesta.estado,
                    }
                )

            if propuesta.estado != EstadoTramite.APROBADO:
                return JsonResponse(
                    {'ok': False, 'mensaje': MSG_04_02}, status=409
                )

            asignacion = obtener_director_activo(propuesta)
            if asignacion is None:
                return JsonResponse(
                    {'ok': False, 'mensaje': MSG_04_04}, status=409
                )

            cargue = CargueUp.objects.create(
                propuesta=propuesta,
                fecha_declaracion=ahora,
                estado_verificacion=EstadoVerificacion.PENDIENTE,
            )

            estado_anterior = propuesta.estado
            propuesta.estado = EstadoTramite.SUBIDO_EN_UP
            propuesta.save(update_fields=['estado', 'fecha_actualizacion'])

            HistorialEstado.objects.create(
                propuesta=propuesta,
                usuario=request.user,
                estado_anterior=estado_anterior,
                estado_nuevo=EstadoTramite.SUBIDO_EN_UP,
                tipo_accion=ACCION_AUDITORIA_AVISO,
                fecha_hora=ahora,
            )

            Notificacion.objects.create(
                usuario=asignacion.director.usuario,
                propuesta=propuesta,
                tipo=TIPO_NOTIFICACION_AVISO,
                mensaje=mensaje_notificacion_aviso(propuesta),
                fecha_creacion=ahora,
            )

            Auditoria.objects.create(
                usuario=request.user,
                accion=ACCION_AUDITORIA_AVISO,
                tabla_afectada='propuesta',
                id_registro_afectado=propuesta.pk,
                detalle=(
                    f"Cargue en UP {cargue.pk} registrado | "
                    f"Transición: {estado_anterior} -> {propuesta.estado}"
                ),
                resultado='Éxito',
                fecha_hora=ahora,
            )

    except Http404:
        raise
    except Exception:
        logger.exception(
            'No se pudo registrar el aviso de cargue en UP de la propuesta %s.',
            id_propuesta,
        )
        return JsonResponse({'ok': False, 'mensaje': MSG_04_05}, status=500)

    return JsonResponse(
        {
            'ok': True,
            'creado': True,
            'duplicado': False,
            'mensaje': MSG_04_01,
            'id_propuesta': propuesta.pk,
            'id_cargue_up': cargue.pk,
            'estado': propuesta.estado,
        }
    )
