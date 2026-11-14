"""SISTRA-11 · Parametrización: vistas de inicio e índice."""
from django.shortcuts import render
from django.views import View

from apps.parametrizacion.permisos import ParametrizarRequeridoMixin, contexto_menu


class InicioView(ParametrizarRequeridoMixin, View):
    """Entrada del módulo. Solo el Administrador (sistema.parametrizar)."""

    def get(self, request):
        return render(request, 'parametrizacion/parametrizacion/inicio.html', {
            **contexto_menu(request.user), 'seccion': 'inicio',
        })
