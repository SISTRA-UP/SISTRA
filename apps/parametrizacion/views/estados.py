"""SISTRA-11 · Parametrización: vistas de estados del proceso (actividades y tipos de rechazo)."""

from django.contrib import messages
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.seguimiento.models import Auditoria
from apps.usuarios.permisos import ParametrizarRequeridoMixin, contexto_menu

from ..forms.estados import ActividadForm, TipoRechazoForm
from ..models import Actividad, TipoRechazo


class EstadosView(ParametrizarRequeridoMixin, View):
    """Lista las etapas generales (actividades/estados) y los tipos de rechazo."""

    template_name = 'parametrizacion/parametrizacion/estados.html'

    def get(self, request):
        actividades = Actividad.objects.order_by('orden')
        tipos_rechazo = TipoRechazo.objects.order_by('nombre')
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'estados',
            'actividades': actividades,
            'tipos_rechazo': tipos_rechazo,
            'form_actividad': ActividadForm(),
            'form_rechazo': TipoRechazoForm(),
        })


class CrearActividadView(ParametrizarRequeridoMixin, View):
    """Crea una nueva etapa (actividad) del proceso."""

    def post(self, request):
        form = ActividadForm(request.POST)
        if form.is_valid():
            actividad = form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Crear etapa del proceso',
                tabla_afectada='actividad',
                id_registro_afectado=actividad.pk,
                detalle=f'Nombre: {actividad.nombre}, Orden: {actividad.orden}, Obligatoria: {actividad.obligatoria}',
                resultado='Éxito',
            )
            messages.success(request, f'Etapa «{actividad.nombre}» creada correctamente.')
        else:
            errores = ' '.join(e for errs in form.errors.values() for e in errs)
            messages.error(request, f'No se pudo crear la etapa: {errores}')
        return redirect('parametrizacion:estados')


class EditarActividadView(ParametrizarRequeridoMixin, View):
    """Edita una etapa (actividad) existente."""

    template_name = 'parametrizacion/parametrizacion/actividad_editar.html'

    def get(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk)
        form = ActividadForm(instance=actividad)
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'estados',
            'actividad': actividad,
            'form': form,
        })

    def post(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk)
        form = ActividadForm(request.POST, instance=actividad)
        if form.is_valid():
            actividad = form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Editar etapa del proceso',
                tabla_afectada='actividad',
                id_registro_afectado=actividad.pk,
                detalle=f'Nombre: {actividad.nombre}, Orden: {actividad.orden}, Estado: {actividad.estado}',
                resultado='Éxito',
            )
            messages.success(request, f'Etapa «{actividad.nombre}» actualizada correctamente.')
            return redirect('parametrizacion:estados')
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'estados',
            'actividad': actividad,
            'form': form,
        })


class EliminarActividadView(ParametrizarRequeridoMixin, View):
    """Elimina una etapa del proceso."""

    def post(self, request, pk):
        actividad = get_object_or_404(Actividad, pk=pk)
        nombre = actividad.nombre
        try:
            actividad.delete()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Eliminar etapa del proceso',
                tabla_afectada='actividad',
                id_registro_afectado=pk,
                detalle=f'Etapa eliminada: {nombre}',
                resultado='Éxito',
            )
            messages.success(request, f'Etapa «{nombre}» eliminada correctamente.')
        except models.ProtectedError:
            messages.error(
                request,
                f'No se puede eliminar la etapa «{nombre}» porque tiene registros asociados. '
                'Puede cambiar su estado a Inactivo desde Editar.'
            )
        return redirect('parametrizacion:estados')


class CrearTipoRechazoView(ParametrizarRequeridoMixin, View):
    """Crea una nueva causal o tipo de rechazo."""

    def post(self, request):
        form = TipoRechazoForm(request.POST)
        if form.is_valid():
            tipo = form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Crear tipo de rechazo',
                tabla_afectada='tipo_rechazo',
                id_registro_afectado=tipo.pk,
                detalle=f'Nombre: {tipo.nombre}',
                resultado='Éxito',
            )
            messages.success(request, f'Tipo de rechazo «{tipo.nombre}» creado correctamente.')
        else:
            errores = ' '.join(e for errs in form.errors.values() for e in errs)
            messages.error(request, f'No se pudo crear el tipo de rechazo: {errores}')
        return redirect('parametrizacion:estados')


class EditarTipoRechazoView(ParametrizarRequeridoMixin, View):
    """Edita un tipo de rechazo existente."""

    template_name = 'parametrizacion/parametrizacion/tipo_rechazo_editar.html'

    def get(self, request, pk):
        tipo = get_object_or_404(TipoRechazo, pk=pk)
        form = TipoRechazoForm(instance=tipo)
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'estados',
            'tipo': tipo,
            'form': form,
        })

    def post(self, request, pk):
        tipo = get_object_or_404(TipoRechazo, pk=pk)
        form = TipoRechazoForm(request.POST, instance=tipo)
        if form.is_valid():
            tipo = form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Editar tipo de rechazo',
                tabla_afectada='tipo_rechazo',
                id_registro_afectado=tipo.pk,
                detalle=f'Nombre: {tipo.nombre}, Estado: {tipo.estado}',
                resultado='Éxito',
            )
            messages.success(request, f'Tipo de rechazo «{tipo.nombre}» actualizado correctamente.')
            return redirect('parametrizacion:estados')
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'estados',
            'tipo': tipo,
            'form': form,
        })


class EliminarTipoRechazoView(ParametrizarRequeridoMixin, View):
    """Elimina una causal o tipo de rechazo."""

    def post(self, request, pk):
        tipo = get_object_or_404(TipoRechazo, pk=pk)
        nombre = tipo.nombre
        try:
            tipo.delete()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Eliminar tipo de rechazo',
                tabla_afectada='tipo_rechazo',
                id_registro_afectado=pk,
                detalle=f'Tipo de rechazo eliminado: {nombre}',
                resultado='Éxito',
            )
            messages.success(request, f'Tipo de rechazo «{nombre}» eliminado correctamente.')
        except models.ProtectedError:
            messages.error(
                request,
                f'No se puede eliminar «{nombre}» porque está en uso en trámites del sistema. '
                'Puede cambiar su estado a Inactivo desde Editar.'
            )
        return redirect('parametrizacion:estados')
