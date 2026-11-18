
"""SISTRA-12 · Reportes: vistas."""

import logging

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import render

from apps.propuestas.forms.aprobacion import (
    RESULTADO_EXITO,
    RESULTADO_FALLO,
)
from apps.reportes.forms.reportes import (
    FormularioReporte,
    MSG_REP_02,
    MSG_REP_04,
    MSG_REP_05,
)
from apps.reportes.services.report_pdf_service import (
    generar_pdf_trabajo_social,
)
from apps.reportes.services.report_service import (
    obtener_datos_reporte_trabajo_social,
)
from apps.seguimiento.models import Auditoria
from apps.personas.models import DirectorCarrera


logger = logging.getLogger(__name__)


def _registrar_auditoria(usuario, accion, resultado, detalle=''):
    """Registra el acceso o intento de descarga del reporte."""
    Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tabla_afectada='reporte',
        id_registro_afectado=None,
        detalle=detalle,
        resultado=resultado,
    )


def _renderizar_reporte(request, formulario, mensaje=None):
    """Renderiza la pantalla principal del módulo de reportes."""
    return render(
        request,
        'reportes/reportes/reportes.html',
        {
            'formulario': formulario,
            'mensaje': mensaje,
            'mensaje_generando': MSG_REP_05,
        },
    )


@login_required
@permission_required('reporte.descargar', raise_exception=True)
def reportes(request):
    """
    Muestra el formulario y permite generar el reporte en PDF.

    GET:
        Muestra el formulario y registra el acceso.

    POST:
        Valida las fechas, consulta los registros y genera el PDF.
    """

    # El administrador puede consultar todas las carreras.
    # El director necesita al menos una asignación activa.
    if not request.user.has_perm('reporte.descargar_todas'):
        tiene_carrera_activa = DirectorCarrera.objects.filter(
            director__usuario=request.user,
            activo=True,
        ).exists()

        if not tiene_carrera_activa:
            raise PermissionDenied

    if request.method == 'GET':
        formulario = FormularioReporte()

        try:
            _registrar_auditoria(
                request.user,
                'reporte_acceso',
                RESULTADO_EXITO,
                'Acceso al módulo de reportes de Trabajo Social.',
            )
        except Exception:
            logger.exception(
                'Error al registrar el acceso al módulo de reportes.'
            )

        return _renderizar_reporte(
            request,
            formulario,
        )

    formulario = FormularioReporte(request.POST)

    if not formulario.is_valid():
        return _renderizar_reporte(
            request,
            formulario,
        )

    fecha_desde = formulario.cleaned_data['filterDateStart']
    fecha_hasta = formulario.cleaned_data['filterDateEnd']

    detalle_rango = (
        f'Fecha desde: {fecha_desde:%d/%m/%Y} | '
        f'Fecha hasta: {fecha_hasta:%d/%m/%Y}'
    )

    try:
        datos = obtener_datos_reporte_trabajo_social(
            request.user,
            date_start=fecha_desde,
            date_end=fecha_hasta,
        )

        if not datos['aprobados'] and not datos['rechazados']:
            _registrar_auditoria(
                request.user,
                'reporte_descarga',
                RESULTADO_FALLO,
                f'{detalle_rango} | No se encontraron registros.',
            )

            return _renderizar_reporte(
                request,
                formulario,
                MSG_REP_02,
            )

        rol_usuario = (
            'Administrador'
            if datos['incluir_carrera']
            else 'Director'
        )

        pdf = generar_pdf_trabajo_social(
            datos,
            rol_usuario,
            {
                'start': fecha_desde,
                'end': fecha_hasta,
            },
        )

        _registrar_auditoria(
            request.user,
            'reporte_descarga',
            RESULTADO_EXITO,
            (
                f'{detalle_rango} | '
                'Reporte de Trabajo Social generado correctamente.'
            ),
        )

        nombre_archivo = (
            f'reporte_trabajo_social_'
            f'{fecha_desde:%Y%m%d}_'
            f'{fecha_hasta:%Y%m%d}.pdf'
        )

        return FileResponse(
            pdf,
            as_attachment=True,
            filename=nombre_archivo,
            content_type='application/pdf',
        )

    except PermissionDenied:
        raise

    except Exception:
        logger.exception(
            'Error al generar el reporte de Trabajo Social. Usuario: %s',
            request.user.pk,
        )

        try:
            _registrar_auditoria(
                request.user,
                'reporte_descarga',
                RESULTADO_FALLO,
                f'{detalle_rango} | Error al generar el reporte.',
            )
        except Exception:
            logger.exception(
                'No se pudo registrar el fallo de generación del reporte.'
            )

        return _renderizar_reporte(
            request,
            formulario,
            MSG_REP_04,
        )
