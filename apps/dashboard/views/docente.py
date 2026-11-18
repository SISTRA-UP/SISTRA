"""Vista del dashboard docente."""

from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.dashboard.servicios.docente import resumen_docente, resumen_notificaciones
from apps.dashboard.services import (
    construir_contexto_director,
    registrar_auditoria_dashboard,
)
from apps.dashboard.views.comun import requiere_rol
from apps.personas.models import DirectorCarrera
from apps.seguimiento.models import Notificacion


@requiere_rol('Director')
@require_GET
def docente(request: HttpRequest) -> HttpResponse:
    """Muestra el resumen del director y accesos a sus bandejas existentes."""
    asignacion = (
        DirectorCarrera.objects.filter(director__usuario=request.user, activo=True)
        .select_related('director', 'carrera')
        .order_by('-fecha_inicio', '-id_director_carrera')
        .first()
    )
    if not asignacion:
        raise PermissionDenied

    registrar_auditoria_dashboard(request.user, 'Director')
    contexto = {
        **construir_contexto_director(request.user, {}),
        **resumen_docente(asignacion),
        **resumen_notificaciones(request.user),
        'vista_dashboard': 'docente',
        'url_bandeja': reverse('propuestas:aprobacion'),
    }
    return render(request, 'dashboard/docente.html', contexto)


@requiere_rol('Director')
@require_POST
def abrir_notificacion(request: HttpRequest, id_notificacion: int) -> HttpResponse:
    """Marca como leída una notificación y señala su propuesta en el dashboard."""
    notificacion = get_object_or_404(
        Notificacion.objects.select_related('propuesta', 'informe'),
        id_notificacion=id_notificacion,
        usuario=request.user,
    )
    if notificacion.fecha_lectura is None:
        notificacion.fecha_lectura = timezone.now()
        notificacion.save(update_fields=['fecha_lectura'])

    if notificacion.propuesta_id:
        destino = reverse('propuestas:aprobacion')
        filtro = urlencode({'buscar': notificacion.propuesta.codigo})
        return redirect(f'{destino}?{filtro}')
    if notificacion.informe_id:
        if notificacion.tipo == 'Subido en UP':
            return redirect(
                'cargue_up:verificacion_informe_detalle',
                id_informe=notificacion.informe_id,
            )
        destino = reverse('informes:aprobacion')
        filtro = urlencode({'buscar': notificacion.informe.codigo})
        return redirect(f'{destino}?{filtro}')
    return redirect('dashboard:docente')
