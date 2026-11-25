"""SISTRA-09 · Notificación de cargue UP – Director (informe): vistas.

Solo el responsable de este requisito edita este archivo.

El Director marca «Aprobado en UP» o «Rechazado en UP» sobre los informes de sus
estudiantes en «Subido en UP» y el estudiante recibe un aviso dentro de SISTRA.
Cada decisión es atómica e idempotente (mismo patrón que SISTRA-04 y SISTRA-07).
"""

import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.forms.verificacion_informe import (
    ACCION_AUDITORIA_CORREGIR,
    ACCION_AUDITORIA_DENEGADO,
    ACCION_AUDITORIA_REAPERTURA,
    ACCION_AUDITORIA_VERIFICAR,
    MSG_09_01,
    MSG_09_02,
    MSG_09_04,
    MSG_09_CORRECCION,
    MSG_09_CORRECCION_NO_DISPONIBLE,
    MSG_09_ERROR,
    POR_PAGINA,
    RESULTADO_BLOQUEADO,
    RESULTADO_EXITO,
    RESULTADO_FALLO,
    TIPO_NOTIFICACION_CORRECCION,
    TIPO_NOTIFICACION_VERIFICACION,
    VISTA_PENDIENTES,
    VISTA_VERIFICADOS,
    BusquedaForm,
    CorreccionForm,
    DecisionForm,
    director_y_carreras,
    estado_informe_para,
    filtrar_por_busqueda,
    informe_del_director_o_404,
    informes_del_director,
    mensaje_notificacion,
    pendientes,
    resultado_de_correccion,
    verificados_corregibles,
)
from apps.cargue_up.models import CargueUp, EstadoVerificacion, HistorialCargueUp
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.procesos.models import EstadoAvance

logger = logging.getLogger(__name__)

DETALLE_DENEGADO = {
    403: 'Acceso sin autorización a la verificación de cargues de informes.',
    404: 'Informe inexistente o fuera de los estudiantes asignados al Director.',
}


def _auditar_denegado(request: HttpRequest, codigo_http: int, id_informe=None) -> None:
    """Registra el intento denegado sin datos del informe ni del formulario."""
    try:
        Auditoria.objects.create(
            usuario=request.user,
            accion=ACCION_AUDITORIA_DENEGADO,
            tabla_afectada='informe',
            id_registro_afectado=id_informe,
            detalle=f'HTTP {codigo_http}. {DETALLE_DENEGADO[codigo_http]}',
            resultado=RESULTADO_BLOQUEADO,
        )
    except Exception:
        # Un fallo de auditoría no debe ocultar la respuesta original.
        logger.exception('No se pudo auditar el acceso denegado a la verificación de informes.')


def auditar_denegados(vista):
    @wraps(vista)
    def ejecutar(request, *args, **kwargs):
        try:
            return vista(request, *args, **kwargs)
        except PermissionDenied:
            _auditar_denegado(request, 403, kwargs.get('id_informe'))
            raise
        except Http404:
            _auditar_denegado(request, 404, kwargs.get('id_informe'))
            raise

    return ejecutar


def _auditar_fallo(request: HttpRequest, accion: str, id_informe: int) -> None:
    """Registra la operación fallida, sin detalles técnicos, fuera de la transacción revertida."""
    try:
        Auditoria.objects.create(
            usuario=request.user,
            accion=accion,
            tabla_afectada='informe',
            id_registro_afectado=id_informe,
            detalle='No se pudo guardar la verificación; no se guardaron cambios.',
            resultado=RESULTADO_FALLO,
        )
    except Exception:
        logger.exception('No se pudo auditar el fallo de la verificación del informe %s.', id_informe)


def _contexto_detalle(informe, *, formulario_decision=None, formulario_correccion=None):
    cargues = list(informe.cargues_up.select_related('director__usuario').order_by('-fecha_declaracion', '-pk'))
    ultimo = cargues[0] if cargues else None
    pendiente = (
        informe.estado == EstadoTramite.SUBIDO_EN_UP
        and ultimo is not None
        and ultimo.estado_verificacion == EstadoVerificacion.PENDIENTE
    )
    resultado_nuevo = resultado_de_correccion(
        informe.estado, ultimo.estado_verificacion if ultimo else None
    )
    historial = (
        HistorialCargueUp.objects.filter(cargue_up__in=cargues)
        .select_related('director__usuario')
        .order_by('-fecha_hora', '-pk')
    )
    return {
        'informe': informe,
        'estudiante': informe.propuesta.proceso.estudiante_carrera.estudiante.usuario,
        'cargues': cargues,
        'ultimo_cargue': ultimo,
        'pendiente': pendiente,
        'resultado_correccion': resultado_nuevo,
        'historial': historial,
        'formulario_decision': formulario_decision,
        'formulario_correccion': formulario_correccion
        or (
            CorreccionForm(
                initial={'id_cargue': ultimo.pk, 'resultado': resultado_nuevo}, resultado_nuevo=resultado_nuevo
            )
            if resultado_nuevo and ultimo
            else None
        ),
        'rechazo': EstadoVerificacion.RECHAZADO_EN_UP,
        'aprobacion': EstadoVerificacion.APROBADO_EN_UP,
    }


@login_required
@require_GET
@auditar_denegados
def lista(request: HttpRequest) -> HttpResponse:
    """«Informes por verificar» de los estudiantes asignados al Director."""
    vista = request.GET.get('vista')
    vista = vista if vista in (VISTA_PENDIENTES, VISTA_VERIFICADOS) else VISTA_PENDIENTES

    formulario = BusquedaForm(request.GET)
    texto = formulario.cleaned_data['buscar'] if formulario.is_valid() else ''

    informes = informes_del_director(request.user)
    informes = pendientes(informes) if vista == VISTA_PENDIENTES else verificados_corregibles(informes)
    informes = filtrar_por_busqueda(informes, texto)
    orden = 'fecha_ultimo_cargue' if vista == VISTA_PENDIENTES else '-fecha_ultimo_cargue'
    pagina = Paginator(informes.order_by(orden, 'pk'), POR_PAGINA).get_page(request.GET.get('page'))

    filas = [
        {
            'informe': informe,
            'estudiante': informe.propuesta.proceso.estudiante_carrera.estudiante.usuario,
            'formulario': DecisionForm(initial={'id_cargue': informe.id_ultimo_cargue}),
        }
        for informe in pagina.object_list
    ]
    return render(
        request,
        'cargue_up/verificacion_informe/lista.html',
        {
            'vista': vista,
            'formulario_busqueda': formulario,
            'pagina': pagina,
            'filas': filas,
            'rechazo': EstadoVerificacion.RECHAZADO_EN_UP,
            'aprobacion': EstadoVerificacion.APROBADO_EN_UP,
        },
    )


@login_required
@require_GET
@auditar_denegados
def detalle(request: HttpRequest, id_informe: int) -> HttpResponse:
    """«Ver detalle»: 404 si el estudiante no es del Director."""
    informe = informe_del_director_o_404(request.user, id_informe)
    return render(
        request,
        'cargue_up/verificacion_informe/detalle.html',
        _contexto_detalle(informe),
    )


@login_required
@require_POST
@auditar_denegados
def decidir(request: HttpRequest, id_informe: int) -> HttpResponse:
    """Registra Aprobado en UP / Rechazado en UP de forma atómica e idempotente."""
    perfil, _ = director_y_carreras(request.user)
    informe_vista = informe_del_director_o_404(request.user, id_informe, etapa_cargue=False)

    formulario = DecisionForm(request.POST)
    if not formulario.is_valid():
        return render(
            request,
            'cargue_up/verificacion_informe/detalle.html',
            _contexto_detalle(informe_vista, formulario_decision=formulario),
            status=400,
        )

    resultado = formulario.cleaned_data['resultado']
    observacion = formulario.cleaned_data['observacion']
    id_cargue = formulario.cleaned_data['id_cargue']

    try:
        with transaction.atomic():
            informe = informe_del_director_o_404(
                request.user, id_informe, bloquear=True, etapa_cargue=False
            )
            cargue = (
                CargueUp.objects.select_for_update()
                .filter(informe=informe)
                .order_by('-fecha_declaracion', '-pk')
                .first()
            )
            # RN-09-01 / EX-01 / EX-02: la decisión queda ligada al cargue que el Director
            # vio; si ya cambió (doble clic, otro Director o recarga del estudiante) no se guarda.
            if (
                informe.estado != EstadoTramite.SUBIDO_EN_UP
                or cargue is None
                or cargue.estado_verificacion != EstadoVerificacion.PENDIENTE
                or cargue.pk != id_cargue
            ):
                messages.warning(request, MSG_09_04)
                return redirect('cargue_up:verificacion_informe_lista')

            ahora = timezone.now()
            estado_anterior = informe.estado
            estado_nuevo = estado_informe_para(resultado)

            cargue.director = perfil
            cargue.estado_verificacion = resultado
            cargue.fecha_verificacion = max(ahora, cargue.fecha_declaracion)
            cargue.observacion = observacion
            cargue.save(
                update_fields=['director', 'estado_verificacion', 'fecha_verificacion', 'observacion']
            )

            informe.estado = estado_nuevo
            informe.save(update_fields=['estado', 'fecha_actualizacion'])

            HistorialEstado.objects.create(
                informe=informe,
                usuario=request.user,
                estado_anterior=estado_anterior,
                estado_nuevo=estado_nuevo,
                observacion=observacion,
                tipo_accion=ACCION_AUDITORIA_VERIFICAR,
                fecha_hora=ahora,
            )
            Notificacion.objects.create(
                usuario=informe.propuesta.proceso.estudiante_carrera.estudiante.usuario,
                informe=informe,
                tipo=TIPO_NOTIFICACION_VERIFICACION,
                mensaje=mensaje_notificacion(resultado, observacion),
                fecha_creacion=ahora,
            )
            Auditoria.objects.create(
                usuario=request.user,
                accion=ACCION_AUDITORIA_VERIFICAR,
                tabla_afectada='informe',
                id_registro_afectado=informe.pk,
                detalle=(
                    f'Cargue en UP {cargue.pk} | Estudiante '
                    f'{informe.propuesta.proceso.estudiante_carrera.estudiante.usuario_id} | '
                    f'Resultado: {resultado} | Transición: {estado_anterior} -> {estado_nuevo}'
                ),
                resultado=RESULTADO_EXITO,
                fecha_hora=ahora,
            )
    except Http404:
        raise
    except Exception:
        logger.exception('No se pudo guardar la verificación del informe %s.', id_informe)
        _auditar_fallo(request, ACCION_AUDITORIA_VERIFICAR, id_informe)
        messages.error(request, MSG_09_ERROR)
        return redirect('cargue_up:verificacion_informe_lista')

    messages.success(
        request,
        MSG_09_01 if resultado == EstadoVerificacion.APROBADO_EN_UP else MSG_09_02,
    )
    return redirect('cargue_up:verificacion_informe_lista')


@login_required
@require_POST
@auditar_denegados
def corregir(request: HttpRequest, id_informe: int) -> HttpResponse:
    """FA-03: corrige la última verificación; conserva la anterior en el historial."""
    perfil, _ = director_y_carreras(request.user)
    informe_vista = informe_del_director_o_404(request.user, id_informe, etapa_cargue=False)

    ultimo_vista = informe_vista.cargues_up.order_by('-fecha_declaracion', '-pk').first()
    resultado_nuevo = resultado_de_correccion(
        informe_vista.estado, ultimo_vista.estado_verificacion if ultimo_vista else None
    )
    if resultado_nuevo is None or request.POST.get('resultado') != resultado_nuevo:
        messages.warning(request, MSG_09_CORRECCION_NO_DISPONIBLE)
        return redirect('cargue_up:verificacion_informe_lista')

    formulario = CorreccionForm(request.POST, resultado_nuevo=resultado_nuevo)
    if not formulario.is_valid():
        return render(
            request,
            'cargue_up/verificacion_informe/detalle.html',
            _contexto_detalle(informe_vista, formulario_correccion=formulario),
            status=400,
        )

    motivo = formulario.cleaned_data['motivo']
    observacion = formulario.cleaned_data['observacion']
    id_cargue = formulario.cleaned_data['id_cargue']

    try:
        with transaction.atomic():
            informe = informe_del_director_o_404(
                request.user, id_informe, bloquear=True, etapa_cargue=False
            )
            cargue = (
                CargueUp.objects.select_for_update()
                .filter(informe=informe)
                .order_by('-fecha_declaracion', '-pk')
                .first()
            )
            resultado_nuevo = resultado_de_correccion(
                informe.estado, cargue.estado_verificacion if cargue else None
            )
            # Sin nuevo cargue y con el estado que dejó la verificación; si no, no se corrige.
            if resultado_nuevo is None or cargue.pk != id_cargue or formulario.cleaned_data['resultado'] != resultado_nuevo:
                messages.warning(request, MSG_09_CORRECCION_NO_DISPONIBLE)
                return redirect('cargue_up:verificacion_informe_lista')

            ahora = timezone.now()
            resultado_anterior = cargue.estado_verificacion
            observacion_anterior = cargue.observacion
            estado_anterior = informe.estado
            estado_nuevo = estado_informe_para(resultado_nuevo)

            HistorialCargueUp.objects.create(
                cargue_up=cargue,
                director=perfil,
                estado_anterior=resultado_anterior,
                estado_nuevo=resultado_nuevo,
                observacion=observacion,
                motivo_correccion=motivo,
                fecha_hora=ahora,
            )
            cargue.director = perfil
            cargue.estado_verificacion = resultado_nuevo
            cargue.fecha_verificacion = max(ahora, cargue.fecha_declaracion)
            cargue.observacion = observacion
            cargue.save(
                update_fields=['director', 'estado_verificacion', 'fecha_verificacion', 'observacion']
            )

            informe.estado = estado_nuevo
            informe.save(update_fields=['estado', 'fecha_actualizacion'])

            HistorialEstado.objects.create(
                informe=informe,
                usuario=request.user,
                estado_anterior=estado_anterior,
                estado_nuevo=estado_nuevo,
                observacion=observacion,
                tipo_accion=ACCION_AUDITORIA_CORREGIR,
                fecha_hora=ahora,
            )

            proceso = informe.propuesta.proceso
            debe_reabrir = (
                resultado_nuevo == EstadoVerificacion.RECHAZADO_EN_UP
                and proceso is not None
                and proceso.estado == EstadoAvance.FINALIZADA
            )

            Notificacion.objects.create(
                usuario=informe.propuesta.proceso.estudiante_carrera.estudiante.usuario,
                informe=informe,
                tipo=TIPO_NOTIFICACION_CORRECCION,
                mensaje=mensaje_notificacion(
                    resultado_nuevo, observacion, corregida=True, proceso_reabierto=debe_reabrir
                ),
                fecha_creacion=ahora,
            )
            Auditoria.objects.create(
                usuario=request.user,
                accion=ACCION_AUDITORIA_CORREGIR,
                tabla_afectada='informe',
                id_registro_afectado=informe.pk,
                detalle=(
                    f'Cargue en UP {cargue.pk} | Resultado: {resultado_anterior} -> {resultado_nuevo} | '
                    f'Transición: {estado_anterior} -> {estado_nuevo} | Motivo: {motivo}'
                    + (f' | Observación anterior: {observacion_anterior}' if observacion_anterior else '')
                ),
                resultado=RESULTADO_EXITO,
                fecha_hora=ahora,
            )
            # E8: si el resultado es Rechazado en UP y el proceso estaba Finalizada,
            # reabrirlo dentro de la misma transacción (decisión D4 del 20/11) después de E7.
            if debe_reabrir:
                estado_proceso_anterior = proceso.estado
                proceso.estado = EstadoAvance.EN_CURSO
                proceso.fecha_finalizacion = None
                proceso.save(update_fields=['estado', 'fecha_finalizacion'])
                Auditoria.objects.create(
                    usuario=request.user,
                    accion=ACCION_AUDITORIA_REAPERTURA,
                    tabla_afectada='proceso_trabajo_social',
                    id_registro_afectado=proceso.pk,
                    detalle=(
                        f'Proceso {proceso.pk} | Estado: {estado_proceso_anterior} -> {EstadoAvance.EN_CURSO} | '
                        f'Informe {informe.pk} | Corrección de verificación en UP por Director ocasionó la reapertura | '
                        f'Motivo: {motivo}'
                    ),
                    resultado=RESULTADO_EXITO,
                    fecha_hora=ahora,
                )
    except Http404:
        raise
    except Exception:
        logger.exception('No se pudo corregir la verificación del informe %s.', id_informe)
        _auditar_fallo(request, ACCION_AUDITORIA_CORREGIR, id_informe)
        messages.error(request, MSG_09_ERROR)
        return redirect('cargue_up:verificacion_informe_lista')

    messages.success(request, MSG_09_CORRECCION)
    return redirect('cargue_up:verificacion_informe_lista')
