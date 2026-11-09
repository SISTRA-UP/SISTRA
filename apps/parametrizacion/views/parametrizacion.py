"""SISTRA-11 · Parametrización: vistas."""
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.personas.models import DirectorCarrera
from apps.seguimiento.models import Auditoria
from apps.usuarios.cargas import PLANTILLA_CSV, ErrorArchivo, log_errores_csv, procesar_csv
from apps.usuarios.models import PERMISO_PARAMETRIZAR, ROL_ESTUDIANTE, CargaMasiva
from apps.usuarios.permisos import (
    AccesoParametrizacionMixin, CrearUsuariosRequeridoMixin, ParametrizarRequeridoMixin,
    contexto_menu,
)
from apps.usuarios.servicios import ErrorCreacion, carrera_del_director, crear_director, crear_usuario

from ..forms.parametrizacion import CargaMasivaForm, CrearDirectorForm, CrearUsuarioForm


def _csv(contenido, nombre):
    respuesta = HttpResponse(contenido, content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = f'attachment; filename="{nombre}"'
    return respuesta


class InicioView(AccesoParametrizacionMixin, View):
    """Entrada del módulo. El Administrador ve el índice de parametrización;
    el Director pasa directo a «Usuarios», que es lo único que puede usar."""

    def get(self, request):
        if not request.user.has_perm(PERMISO_PARAMETRIZAR):
            return redirect('parametrizacion:usuarios')
        return render(request, 'parametrizacion/parametrizacion/inicio.html', {
            **contexto_menu(request.user), 'seccion': 'inicio',
        })


class UsuariosView(CrearUsuariosRequeridoMixin, View):
    """Pantalla del Director: crear estudiantes uno a uno y por carga masiva."""
    template_name = 'parametrizacion/parametrizacion/usuarios.html'

    def get(self, request):
        return self._mostrar(request, CrearUsuarioForm())

    def post(self, request):
        carrera = carrera_del_director(request.user)
        form = CrearUsuarioForm(request.POST)
        if carrera is None:
            form.add_error(None, 'No tiene una carrera asignada.')
        elif form.is_valid():
            datos = form.cleaned_data
            try:
                usuario = crear_usuario(
                    nombre=datos['nombre'], apellido=datos['apellido'],
                    cedula=datos['cedula'], correo=datos['correo'],
                    telefono=datos['telefono'], rol=ROL_ESTUDIANTE,
                    carrera=carrera, creado_por=request.user,
                )
            except ErrorCreacion as error:
                form.add_error(None, error.mensaje)
                Auditoria.objects.create(
                    usuario=request.user, accion='Crear usuario', tabla_afectada='usuario',
                    detalle=error.mensaje[:500], resultado='Fallo',
                )
            else:
                messages.success(
                    request,
                    f'Estudiante creado. La contraseña temporal se envió a '
                    f'{usuario.correo_institucional}.',
                )
                return redirect('parametrizacion:usuarios')
        return self._mostrar(request, form)

    def _mostrar(self, request, form):
        carga = None
        try:
            carga = CargaMasiva.objects.filter(
                pk=int(request.GET.get('carga', '')), usuario=request.user
            ).first()
        except ValueError:
            pass
        return render(request, self.template_name, {
            'form': form,
            'carrera': carrera_del_director(request.user),
            'carga': carga,
            'filas': carga.filas.order_by('numero_fila')[:100] if carga else [],
            'max_filas': settings.CARGA_MASIVA_MAX_FILAS,
            'max_mb': settings.CARGA_MASIVA_MAX_MB,
            **contexto_menu(request.user),
            'seccion': 'usuarios',
        })


class PlantillaCsvView(CrearUsuariosRequeridoMixin, View):
    def get(self, request):
        return _csv(PLANTILLA_CSV.encode('utf-8-sig'), 'plantilla_estudiantes.csv')


class CargaMasivaView(CrearUsuariosRequeridoMixin, View):
    def post(self, request):
        destino = reverse('parametrizacion:usuarios')
        carrera = carrera_del_director(request.user)
        if carrera is None:
            messages.error(request, 'No tiene una carrera asignada.')
            return redirect(destino)
        form = CargaMasivaForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, ' '.join(e for errores in form.errors.values() for e in errores))
            return redirect(destino)
        try:
            carga = procesar_csv(
                form.cleaned_data['archivo'], usuario=request.user, carrera_permitida=carrera
            )
        except ErrorArchivo as error:
            Auditoria.objects.create(
                usuario=request.user, accion='Carga masiva de estudiantes',
                tabla_afectada='carga_masiva', detalle=error.mensaje[:500], resultado='Fallo',
            )
            messages.error(request, error.mensaje)
            return redirect(destino)
        return redirect(f'{destino}?carga={carga.pk}')


class LogCargaView(CrearUsuariosRequeridoMixin, View):
    def get(self, request, pk):
        # Cada Director solo descarga el log de sus propias cargas.
        carga = get_object_or_404(CargaMasiva, pk=pk, usuario=request.user)
        return _csv(log_errores_csv(carga), f'errores_carga_{carga.pk}.csv')


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
                    nombre=datos['nombre'], apellido=datos['apellido'],
                    cedula=datos['cedula'], correo=datos['correo'],
                    telefono=datos['telefono'], carrera=datos['carrera'],
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