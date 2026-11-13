"""
signals.py — Evento de notificación interna al Director (regla 4).

Este módulo NO importa modelos al nivel superior para evitar importaciones circulares.
Registrar en apps.py:  def ready(self): from . import signals  # noqa
"""
from django.dispatch import Signal, receiver

# Se emite desde PropuestaTrabajoSocial.enviar()
propuesta_enviada = Signal()


@receiver(propuesta_enviada)
def notificar_director(sender, propuesta, es_reenvio=False, **kwargs):
    from .models import Notificacion

    if not propuesta.director_id:
        return
    accion = "reenviado" if es_reenvio else "enviado"
    Notificacion.objects.create(
        destinatario=propuesta.director,
        mensaje=(
            f"{propuesta.estudiante.get_full_name() or propuesta.estudiante} ha {accion} "
            f"la propuesta «{propuesta.titulo}» para tu revisión."
        ),
        url="",  # TODO: enlazar a la vista de revisión del Director cuando exista
    )
