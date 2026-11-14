"""SISTRA-08 · Pantalla «Cargue en UP» del informe."""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.parametrizacion.models import Parametro

from . import aviso_informe_servicio as servicio

logger = logging.getLogger(__name__)

PERMISO = 'cargue_up.avisar'            #Debe reutilizarse en SISTRA-04 y SISTRA-08, porque es el mismo permiso de negocio.
CLAVE_URL_UP = 'cargue_up.url_plataforma' 

MENSAJES = {
    'exito': (messages.SUCCESS, 'Listo. Avisamos a tu Director que subiste el informe a la Plataforma UP.'),   # MSG-08-02
    'no_aprobado': (messages.WARNING, 'El informe debe estar aprobado para avisar el cargue.'),                # MSG-08-05
    'duplicado': (messages.INFO, 'Ya avisaste el cargue de este informe. No se duplicó el aviso.'),
    'sin_permiso': (messages.ERROR, 'No tienes permiso para realizar esta acción.'),
    'falla': (messages.ERROR, 'No pudimos completar la acción. Inténtalo de nuevo.'),                          # MSG-08-04
}


def _estado_pantalla(informe):
    """Define cómo se pinta la tarjeta: bloqueado, habilitado o cargado."""
    if informe is None:
        return 'bloqueado'
    if informe.estado == servicio.APROBADO:
        return 'habilitado'
    if informe.estado in (servicio.SUBIDO_EN_UP, servicio.APROBADO_EN_UP):
        return 'cargado'
    return 'bloqueado'


@login_required
@permission_required(PERMISO, raise_exception=True)
def inicio(request):
    informe = servicio.informe_del_estudiante(request.user)
    estado = _estado_pantalla(informe)
    ultimo_cargue = (
        informe.cargues_up.order_by('-fecha_declaracion').first() if informe else None
    )
    url_up = (
        Parametro.objects.filter(clave=CLAVE_URL_UP).values_list('valor', flat=True).first()
    )
    return render(request, 'cargue_up/aviso_informe/inicio.html', {
        'informe': informe,
        'estado': estado,
        'ultimo_cargue': ultimo_cargue,
        'url_up': url_up,
    })


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