"""SISTRA-11 · Alertas y plazos: vista (solo Administrador)."""
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.views import View

from apps.parametrizacion.permisos import ParametrizarRequeridoMixin, contexto_menu

from apps.parametrizacion import servicios
from apps.parametrizacion.forms.alertas import AlertasForm

CAMPOS_A_CLAVES = {
    'verde_hasta_dias': 'semaforo.verde_hasta_dias',
    'amarillo_hasta_dias': 'semaforo.amarillo_hasta_dias',
    'frecuencia_recordatorio_dias': 'recordatorio.frecuencia_dias',
    'dias_archivado_propuesta': 'dias_archivado_propuesta_rechazada',
    'dias_archivado_informe': 'dias_archivado_informe_rechazado',
    'url_up': 'url_up',
}


class AlertasView(ParametrizarRequeridoMixin, View):
    template_name = 'parametrizacion/parametrizacion/alertas.html'

    def get(self, request):
        actuales = {
            campo: servicios.obtener(clave) or '' for campo, clave in CAMPOS_A_CLAVES.items()
        }
        return self._mostrar(request, AlertasForm(initial=actuales))

    def post(self, request):
        form = AlertasForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                cambios = sum(
                    servicios.guardar(clave, form.cleaned_data[campo], request.user)
                    for campo, clave in CAMPOS_A_CLAVES.items()
                )
            if cambios:
                messages.success(request, 'Los parámetros se guardaron correctamente.')
            else:
                messages.success(request, 'No hubo cambios que guardar.')
            return redirect('parametrizacion:alertas')
        return self._mostrar(request, form)

    def _mostrar(self, request, form):
        return render(request, self.template_name, {
            'form': form,
            'verde': servicios.obtener_entero('semaforo.verde_hasta_dias'),
            'amarillo': servicios.obtener_entero('semaforo.amarillo_hasta_dias'),
            **contexto_menu(request.user), 'seccion': 'alertas',
        })