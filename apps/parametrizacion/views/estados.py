"""SISTRA-11 · Parametrización: vistas de estados del proceso (actividades y tipos de rechazo)."""

from django.contrib import messages
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.seguimiento.models import Auditoria
from apps.usuarios.permisos import ParametrizarRequeridoMixin, contexto_menu

from ..forms.estados import ActividadForm, TipoRechazoForm
from ..models import Actividad, TipoRechazo


ETAPAS_DEFECTO = [
    {
        'orden': 1,
        'nombre': 'En revisión',
        'descripcion': 'Propuesta o informe radicado y en proceso de evaluación académica y metodológica.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 2,
        'nombre': 'Requiere modificación',
        'descripcion': 'Devuelto al estudiante con observaciones para que realice los ajustes solicitados.',
        'obligatoria': False,
        'estado': 'Activo',
    },
    {
        'orden': 3,
        'nombre': 'Aprobado',
        'descripcion': 'Aprobación académica formal en SISTRA para habilitar el cargue en Plataforma UP.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 4,
        'nombre': 'Subido en UP',
        'descripcion': 'El estudiante declara formalmente que radicó el documento aprobado en la Plataforma UP.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 5,
        'nombre': 'Aprobado en UP',
        'descripcion': 'El Director valida el soporte institucional en la Plataforma UP y concluye el trámite.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 6,
        'nombre': 'Rechazado',
        'descripcion': 'Trámite no aprobado por incumplimiento de requisitos o plazo reglamentario vencido.',
        'obligatoria': False,
        'estado': 'Activo',
    },
]

TIPOS_RECHAZO_DEFECTO = [
    {
        'nombre': 'Documentación incompleta',
        'descripcion': 'Falta de soportes, cartas de aceptación de la entidad receptora o anexos obligatorios.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Incumplimiento de requisitos de plantilla',
        'descripcion': 'El documento no se ajusta a la plantilla oficial de la Universidad o presenta problemas de formato.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Objetivos o plan de trabajo no pertinentes',
        'descripcion': 'Las actividades propuestas no corresponden al perfil profesional o a los lineamientos de Trabajo Social.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Inconsistencia en cronograma o dedicación horaria',
        'descripcion': 'Las fechas programadas o la distribución de horas no cumplen la reglamentación académica vigente.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Falta de aval de la entidad receptora',
        'descripcion': 'No se adjunta constancia formal firmada por el responsable de la institución o comunidad donde se ejecuta.',
        'estado': 'Activo',
    },
]


def asegurar_estados_defecto():
    """Siembra de forma idempotente las etapas generales y tipos de rechazo si faltan."""
    for etapa in ETAPAS_DEFECTO:
        if not Actividad.objects.filter(nombre__iexact=etapa['nombre']).exists():
            orden = etapa['orden']
            while Actividad.objects.filter(orden=orden).exists():
                orden += 1
            Actividad.objects.create(
                nombre=etapa['nombre'],
                descripcion=etapa['descripcion'],
                orden=orden,
                obligatoria=etapa['obligatoria'],
                estado=etapa['estado'],
            )

    for tipo in TIPOS_RECHAZO_DEFECTO:
        if not TipoRechazo.objects.filter(nombre__iexact=tipo['nombre']).exists():
            TipoRechazo.objects.create(
                nombre=tipo['nombre'],
                descripcion=tipo['descripcion'],
                estado=tipo['estado'],
            )


class EstadosView(ParametrizarRequeridoMixin, View):
    """Lista las etapas generales (actividades/estados) y los tipos de rechazo."""

    template_name = 'parametrizacion/parametrizacion/estados.html'

    def get(self, request):
        asegurar_estados_defecto()
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
