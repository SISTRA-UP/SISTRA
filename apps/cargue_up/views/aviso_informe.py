"""SISTRA-08 · Pantalla «Cargue en UP» del informe."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.parametrizacion.servicios import obtener

from . import aviso_informe_servicio as servicio

logger = logging.getLogger(__name__)

PERMISO = 'cargue_up.avisar'            # Debe reutilizarse en SISTRA-04 y SISTRA-08, porque es el mismo permiso de negocio.
CLAVE_URL_UP = 'url_up'                 # Misma clave que usa SISTRA-03.

MENSAJES = {
    'exito': (messages.SUCCESS, 'Listo. Avisamos a tu Director que subiste el informe a la Plataforma UP.'),   # MSG-08-02
    'no_aprobado': (messages.WARNING, 'El informe debe estar aprobado para avisar el cargue.'),                # MSG-08-05
    'duplicado': (messages.INFO, 'Ya avisaste el cargue de este informe. No se duplicó el aviso.'),
    'sin_permiso': (messages.ERROR, 'No tienes permiso para realizar esta acción.'),
    'falla': (messages.ERROR, 'No pudimos completar la acción. Inténtalo de nuevo.'),                          # MSG-08-04
    'sin_enlace': (messages.ERROR, 'El enlace a la Plataforma UP no está disponible por ahora.'),
}


def _url_up():
    valor = obtener(CLAVE_URL_UP)
    return valor.strip() if valor and valor.strip().startswith('https://') else None

def _estado_pantalla(informe):
    """Define cómo se pinta la tarjeta: bloqueado, habilitado o cargado."""
    if informe is None:
        return 'bloqueado'
    if informe.estado == servicio.APROBADO:
        return 'habilitado'
    if informe.estado in (servicio.SUBIDO_EN_UP, servicio.APROBADO_EN_UP):
        return 'cargado'
    return 'bloqueado'


def _informe_aprobado_o_bloquear(request, accion):
    """Informe propio y Aprobado; si no, audita Bloqueado y deja MSG-08-05."""
    informe = servicio.informe_del_estudiante(request.user)
    if informe is None or informe.estado != servicio.APROBADO:
        servicio.auditar(
            request.user, accion, informe, servicio.RESULTADO_BLOQUEADO, 'no_aprobado')
        messages.add_message(request, *MENSAJES['no_aprobado'])
        return None
    return informe


@login_required
@permission_required(PERMISO, raise_exception=True)
def inicio(request):
    informe = servicio.informe_del_estudiante(request.user)
    estado = _estado_pantalla(informe)
    ultimo_cargue = (
        informe.cargues_up.order_by('-fecha_declaracion').first() if informe else None
    )
    return render(request, 'cargue_up/aviso_informe/inicio.html', {
        'informe': informe,
        'estado': estado,
        'ultimo_cargue': ultimo_cargue,
        'url_up': _url_up(),
    })


@login_required
@permission_required(PERMISO, raise_exception=True)
def ir_a_up(request):
    informe = _informe_aprobado_o_bloquear(request, servicio.ACCION_IR_UP)
    if informe is None:
        return redirect('cargue_up:aviso_informe')
    url_up = _url_up()
    if not url_up:
        servicio.auditar(
            request.user, servicio.ACCION_IR_UP, informe,
            servicio.RESULTADO_BLOQUEADO, 'sin_url_up')
        messages.add_message(request, *MENSAJES['sin_enlace'])
        return redirect('cargue_up:aviso_informe')
    servicio.auditar(request.user, servicio.ACCION_IR_UP, informe, servicio.RESULTADO_EXITO)
    return redirect(url_up)


@login_required
@permission_required(PERMISO, raise_exception=True)
def descargar(request):
    informe = _informe_aprobado_o_bloquear(request, servicio.ACCION_DESCARGAR)
    if informe is None:
        return redirect('cargue_up:aviso_informe')
    # El PDF del informe aún no se genera: se audita como Fallo (igual que SISTRA-03).
    servicio.auditar(
        request.user, servicio.ACCION_DESCARGAR, informe,
        servicio.RESULTADO_FALLO, 'documento_no_disponible')
    messages.add_message(request, *MENSAJES['falla'])                  # MSG-08-04
    return redirect('cargue_up:aviso_informe')


@login_required
@permission_required(PERMISO, raise_exception=True)
@require_POST
def confirmar(request):
    try:
        servicio.registrar_subido_en_up(request.user, request.POST.get('id_informe'))
        clave = 'exito'
    except servicio.AvisoInformeError as error:
        clave = error.codigo if error.codigo in MENSAJES else 'falla'
    except Exception:
        logger.exception('Falla inesperada al registrar Subido en UP (informe)')
        clave = 'falla'
    nivel, texto = MENSAJES[clave]
    messages.add_message(request, nivel, texto)
    return redirect('cargue_up:aviso_informe')