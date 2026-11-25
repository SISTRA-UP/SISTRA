"""Catálogos de facultades y carreras (SISTRA-11)."""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.parametrizacion.permisos import ParametrizarRequeridoMixin, contexto_menu
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Estado

from ..forms.facultades_carreras import CarreraForm, FacultadForm
from ..models import Carrera, Facultad


def _auditar(request, accion, tabla, registro, detalle, resultado):
    Auditoria.objects.create(
        usuario=request.user,
        accion=accion,
        tabla_afectada=tabla,
        id_registro_afectado=registro.pk if registro else None,
        detalle=detalle,
        resultado=resultado,
    )


def _detalle_cambios(anteriores, nuevos):
    cambios = [
        f'{campo}: {valor_anterior} → {nuevos[campo]}'
        for campo, valor_anterior in anteriores.items()
        if valor_anterior != nuevos[campo]
    ]
    return '; '.join(cambios) if cambios else 'Sin cambios'


class AccesoFacultadesCarrerasRequeridoMixin(ParametrizarRequeridoMixin):
    """Registra en auditoría los intentos autenticados bloqueados por permiso."""

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            _auditar(
                self.request,
                'Acceso bloqueado a facultades y carreras',
                'facultad_carrera',
                None,
                f'Ruta: {self.request.path}',
                'Bloqueado',
            )
        return super().handle_no_permission()


class FacultadesCarrerasView(AccesoFacultadesCarrerasRequeridoMixin, View):
    template_name = 'parametrizacion/parametrizacion/facultades_carreras.html'

    def get(self, request):
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'facultades_carreras',
            'facultades': Facultad.objects.order_by('nombre', 'pk'),
            'carreras': Carrera.objects.select_related('facultad').order_by('facultad__nombre', 'nombre', 'pk'),
        })


class FacultadFormView(AccesoFacultadesCarrerasRequeridoMixin, View):
    template_name = 'parametrizacion/parametrizacion/facultad_form.html'

    def get(self, request, pk=None):
        facultad = get_object_or_404(Facultad, pk=pk) if pk else None
        return self._mostrar(request, FacultadForm(instance=facultad), facultad)

    def post(self, request, pk=None):
        facultad = get_object_or_404(Facultad, pk=pk) if pk else None
        estado_anterior = facultad.estado if facultad else None
        valores_anteriores = ({
            'Nombre': facultad.nombre,
            'Descripción': facultad.descripcion,
            'Estado': facultad.estado,
        } if facultad else None)
        form = FacultadForm(request.POST, instance=facultad)
        accion = 'Editar facultad' if facultad else 'Crear facultad'
        if not form.is_valid():
            _auditar(request, accion, 'facultad', facultad, 'Formulario inválido.', 'Fallo')
            return self._mostrar(request, form, facultad)

        estado_nuevo = form.cleaned_data['estado']
        inactivacion = estado_anterior == Estado.ACTIVO and estado_nuevo == Estado.INACTIVO
        accion_auditoria = 'Inactivar facultad' if inactivacion else accion
        try:
            with transaction.atomic():
                guardada = form.save()
                detalle = (
                    _detalle_cambios(valores_anteriores, {
                        'Nombre': guardada.nombre,
                        'Descripción': guardada.descripcion,
                        'Estado': guardada.estado,
                    })
                    if valores_anteriores is not None
                    else f'Nombre: {guardada.nombre}, Estado: {guardada.estado}'
                )
                _auditar(
                    request, accion_auditoria, 'facultad', guardada,
                    detalle, 'Éxito',
                )
        except IntegrityError:
            form.add_error('nombre', 'Ya existe una facultad con ese nombre.')
            _auditar(request, accion_auditoria, 'facultad', facultad, 'Conflicto al guardar el nombre.', 'Fallo')
            return self._mostrar(request, form, facultad)

        messages.success(request, f'Facultad «{guardada.nombre}» guardada correctamente.')
        return redirect('parametrizacion:facultades_carreras')

    def _mostrar(self, request, form, facultad):
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'facultades_carreras',
            'form': form,
            'facultad': facultad,
        })


class CarreraFormView(AccesoFacultadesCarrerasRequeridoMixin, View):
    template_name = 'parametrizacion/parametrizacion/carrera_form.html'

    def get(self, request, pk=None):
        carrera = get_object_or_404(Carrera, pk=pk) if pk else None
        return self._mostrar(request, CarreraForm(instance=carrera), carrera)

    def post(self, request, pk=None):
        carrera = get_object_or_404(Carrera, pk=pk) if pk else None
        estado_anterior = carrera.estado if carrera else None
        valores_anteriores = ({
            'Nombre': carrera.nombre,
            'Código': carrera.codigo,
            'Facultad': carrera.facultad.nombre,
            'Estado': carrera.estado,
        } if carrera else None)
        form = CarreraForm(request.POST, instance=carrera)
        accion = 'Editar carrera' if carrera else 'Crear carrera'
        if not form.is_valid():
            _auditar(request, accion, 'carrera', carrera, 'Formulario inválido.', 'Fallo')
            return self._mostrar(request, form, carrera)

        estado_nuevo = form.cleaned_data['estado']
        inactivacion = estado_anterior == Estado.ACTIVO and estado_nuevo == Estado.INACTIVO
        accion_auditoria = 'Inactivar carrera' if inactivacion else accion
        try:
            with transaction.atomic():
                guardada = form.save()
                detalle = (
                    _detalle_cambios(valores_anteriores, {
                        'Nombre': guardada.nombre,
                        'Código': guardada.codigo,
                        'Facultad': guardada.facultad.nombre,
                        'Estado': guardada.estado,
                    })
                    if valores_anteriores is not None
                    else f'Nombre: {guardada.nombre}, Código: {guardada.codigo}, '
                    f'Facultad: {guardada.facultad.nombre}, Estado: {guardada.estado}'
                )
                _auditar(
                    request, accion_auditoria, 'carrera', guardada,
                    detalle, 'Éxito',
                )
        except IntegrityError:
            form.add_error(None, 'No se pudo guardar la carrera. Revise el código y el nombre de la facultad.')
            _auditar(request, accion_auditoria, 'carrera', carrera, 'Conflicto al guardar la carrera.', 'Fallo')
            return self._mostrar(request, form, carrera)

        messages.success(request, f'Carrera «{guardada.nombre}» guardada correctamente.')
        return redirect('parametrizacion:facultades_carreras')

    def _mostrar(self, request, form, carrera):
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'facultades_carreras',
            'form': form,
            'carrera': carrera,
        })
