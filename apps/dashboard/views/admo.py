"""Vista del dashboard de administración."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.dashboard.services import registrar_auditoria_dashboard
from apps.dashboard.views.comun import requiere_rol


@requiere_rol('Administrador')
@require_GET
def admo(request: HttpRequest) -> HttpResponse:
    """Muestra la portada de administración."""
    registrar_auditoria_dashboard(request.user, 'Administrador')
    return render(request, 'dashboard/admo.html')
