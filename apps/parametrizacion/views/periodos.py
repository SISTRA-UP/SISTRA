"""SISTRA-11 · Periodo académico: vistas (solo Administrador)."""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.seguimiento.models import Auditoria
from apps.parametrizacion.permisos import ParametrizarRequeridoMixin, contexto_menu

from ..forms.periodos import PeriodoForm
from ..models import EstadoPeriodo, PeriodoAcademico


class PeriodosView(ParametrizarRequeridoMixin, View):
    def get(self, request):
        return render(request, 'parametrizacion/parametrizacion/periodos.html', {
            'periodos': PeriodoAcademico.objects.order_by('-fecha_inicio'),
            **contexto_menu(request.user), 'seccion': 'periodos',
        })


class PeriodoFormView(ParametrizarRequeridoMixin, View):
    template_name = 'parametrizacion/parametrizacion/periodo_form.html'

    def get(self, request, pk=None):
        periodo = get_object_or_404(PeriodoAcademico, pk=pk) if pk else None
        return self._mostrar(request, PeriodoForm(periodo=periodo), periodo)

    def post(self, request, pk=None):
        periodo = get_object_or_404(PeriodoAcademico, pk=pk) if pk else None
        form = PeriodoForm(request.POST, periodo=periodo)
        conflicto = None
        if form.is_valid():
            datos = form.cleaned_data
            if datos['estado'] == EstadoPeriodo.VIGENTE:
                conflicto = (
                    PeriodoAcademico.objects.filter(estado=EstadoPeriodo.VIGENTE)
                    .exclude(pk=periodo.pk if periodo else None)
                    .first()
                )
            if conflicto is None or request.POST.get('confirmar') == '1':
                try:
                    guardado = self._guardar(request, periodo, datos, conflicto)
                except IntegrityError:
                    form.add_error(
                        None, 'No se pudo guardar el periodo. Revise el nombre y las fechas.'
                    )
                    Auditoria.objects.create(
                        usuario=request.user, accion='Guardar periodo académico',
                        tabla_afectada='periodo_academico', detalle=datos['nombre'],
                        resultado='Fallo',
                    )
                else:
                    messages.success(request, f'Periodo {guardado.nombre} guardado correctamente.')
                    return redirect('parametrizacion:periodos')
        return self._mostrar(request, form, periodo, conflicto)

    def _guardar(self, request, periodo, datos, conflicto):
        with transaction.atomic():
            if conflicto is not None:
                PeriodoAcademico.objects.filter(pk=conflicto.pk).update(estado=EstadoPeriodo.CERRADO)
                Auditoria.objects.create(
                    usuario=request.user, accion='Cerrar periodo académico',
                    tabla_afectada='periodo_academico', id_registro_afectado=conflicto.pk,
                    detalle=f'{conflicto.nombre}: Vigente → Cerrado (se definió otro periodo vigente).',
                    resultado='Éxito',
                )
            es_nuevo = periodo is None
            if es_nuevo:
                periodo = PeriodoAcademico()
            for campo, valor in datos.items():
                setattr(periodo, campo, valor)
            periodo.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Crear periodo académico' if es_nuevo else 'Editar periodo académico',
                tabla_afectada='periodo_academico', id_registro_afectado=periodo.pk,
                detalle=periodo.nombre, resultado='Éxito',
            )
        return periodo

    def _mostrar(self, request, form, periodo, conflicto=None):
        return render(request, self.template_name, {
            'form': form, 'periodo': periodo, 'conflicto': conflicto,
            **contexto_menu(request.user), 'seccion': 'periodos',
        })