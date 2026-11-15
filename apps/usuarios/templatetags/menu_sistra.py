"""SISTRA-10 · Roles: etiqueta que alimenta el menú por permisos.

El parcial `usuarios/roles/_menu.html` carga esta etiqueta por su cuenta, así
que la plantilla que lo incluye no tiene que pasarle contexto ni hacer
`{% load %}`: le basta `{% include %}`.
"""

from django import template

from apps.usuarios.permisos import opciones_visibles

register = template.Library()


@register.simple_tag(takes_context=True)
def menu_por_permisos(context):
    """Las opciones visibles para el usuario de la petición en curso."""
    peticion = context.get('request')
    usuario = getattr(peticion, 'user', None)
    if usuario is None:
        # Sin `request` en el contexto queda el `user` del context processor.
        usuario = context.get('user')
    return opciones_visibles(usuario)
