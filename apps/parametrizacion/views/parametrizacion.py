"""SISTRA-11 · Parametrización: vistas de inicio e índice."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views import View

from apps.seguimiento.models import Auditoria
from apps.usuarios.permisos import ParametrizarRequeridoMixin, contexto_menu
from apps.usuarios.servicios import ErrorCreacion, crear_director
from apps.personas.models import DirectorCarrera

from ..forms.parametrizacion import CrearDirectorForm


class InicioView(ParametrizarRequeridoMixin, View):
    """Entrada del módulo. Solo el Administrador (sistema.parametrizar)."""

    def get(self, request):
        return render(request, 'parametrizacion/parametrizacion/inicio.html', {
            **contexto_menu(request.user), 'seccion': 'inicio',
        })


class DirectoresView(ParametrizarRequeridoMixin, View):
    """Solo el Administrador: crea directores y los asigna a su carrera."""
    template_name = 'parametrizacion/parametrizacion/directores.html'

    def get(self, request):
        return self._mostrar(request, CrearDirectorForm())

    def post(self, request):
        form = CrearDirectorForm(request.POST)
        if form.is_valid():
            datos = form.cleaned_data
            try:
                director = crear_director(
                    nombre=datos['nombre'],
                    cedula=datos['cedula'], correo=datos['correo'],
                    carrera=datos['carrera'],
                    creado_por=request.user,
                )
            except ErrorCreacion as error:
                form.add_error(None, error.mensaje)
                Auditoria.objects.create(
                    usuario=request.user, accion='Crear director', tabla_afectada='usuario',
                    detalle=error.mensaje[:500], resultado='Fallo',
                )
            else:
                messages.success(
                    request,
                    f'Director creado y asignado a {datos["carrera"].nombre}. La contraseña '
                    f'temporal se envió a {director.correo_institucional}.',
                )
                return redirect('parametrizacion:directores')
        return self._mostrar(request, form)

    def _mostrar(self, request, form):
        asignaciones = (
            DirectorCarrera.objects.select_related('director__usuario', 'carrera')
            .filter(activo=True).order_by('carrera__nombre')
        )
        return render(request, self.template_name, {
            'form': form, 'asignaciones': asignaciones,
            **contexto_menu(request.user), 'seccion': 'directores',
        })
