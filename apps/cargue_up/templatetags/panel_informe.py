"""SISTRA-08 · Datos del panel «Mi informe» dentro de la pantalla «Cargue en UP»."""

from django import template

from apps.cargue_up.views import aviso_informe as vista
from apps.cargue_up.views import aviso_informe_servicio as servicio

register = template.Library()


@register.simple_tag(takes_context=True)
def panel_informe(context):
    usuario = context['request'].user
    informe = servicio.informe_del_estudiante(usuario)
    ultimo_cargue = informe.cargues_up.order_by('-fecha_declaracion').first() if informe else None
    return {
        'informe': informe,
        'estado': vista._estado_pantalla(informe),
        'url_up': vista._url_up(),
        'ultimo_cargue': ultimo_cargue,
    }