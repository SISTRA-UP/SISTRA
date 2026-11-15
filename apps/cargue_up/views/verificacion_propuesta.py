
"""SISTRA-05 · Notificación de cargue UP – Director: vistas."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.forms.aviso_propuesta import TIPO_NOTIFICACION_AVISO
from apps.personas.models import Director
from apps.seguimiento.models import Notificacion


@login_required
@require_GET
def notificaciones_director(request):
    """Muestra al Director sus notificaciones de propuestas cargadas en UP."""

    if not Director.objects.filter(usuario=request.user).exists():
        raise PermissionDenied

    notificaciones = (
        Notificacion.objects
        .filter(
            usuario=request.user,
            tipo=TIPO_NOTIFICACION_AVISO,
            propuesta__isnull=False,
        )
        .select_related("propuesta")
        .order_by("-fecha_creacion")
    )

    total_no_leidas = notificaciones.filter(
        fecha_lectura__isnull=True
    ).count()

    return render(
        request,
        "cargue_up/notificaciones_director.html",
        {
            "notificaciones": notificaciones,
            "total_no_leidas": total_no_leidas,
        },
    )


@login_required
@require_POST
def marcar_notificacion_leida(request, id_notificacion):
    """Marca como leída una notificación perteneciente al Director."""

    if not Director.objects.filter(usuario=request.user).exists():
        raise PermissionDenied

    notificacion = get_object_or_404(
        Notificacion,
        id_notificacion=id_notificacion,
        usuario=request.user,
        tipo=TIPO_NOTIFICACION_AVISO,
        propuesta__isnull=False,
    )

    if notificacion.fecha_lectura is None:
        notificacion.fecha_lectura = timezone.now()
        notificacion.save(update_fields=["fecha_lectura"])

    return redirect("cargue_up:notificaciones_director")
