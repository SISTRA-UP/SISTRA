"""PRO-16 · Datos del panel «Documentos extra» dentro de la pantalla «Cargue UP»."""

from django import template

from apps.cargue_up.forms import documentos_extra as servicio

register = template.Library()


@register.simple_tag(takes_context=True)
def panel_documentos_extra(context):
    """None mientras el informe no esté en «Aprobado en UP»: el panel no se muestra."""
    return servicio.estado_del_estudiante(context['request'].user)
