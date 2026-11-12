"""SISTRA-11 · Parametrización: vistas de documentos y formatos."""

import csv
import os

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.seguimiento.models import Auditoria
from apps.parametrizacion.permisos import ParametrizarRequeridoMixin, contexto_menu
from apps.parametrizacion import servicios as param_servicios

from ..forms.documentos import PlantillaForm, VersionPlantillaForm
from ..models import Plantilla, VersionPlantilla

# Extensiones permitidas según tipo de plantilla
_EXTENSIONES_POR_TIPO = {
    'propuesta': ('.docx',),
    'csv':       ('.csv',),
}
_EXTENSIONES_DEFAULT = ('.docx', '.xlsx', '.csv', '.pdf')


def _extensiones_para(tipo):
    return _EXTENSIONES_POR_TIPO.get(tipo, _EXTENSIONES_DEFAULT)


def _max_mb_para(tipo):
    if tipo == 'csv':
        return param_servicios.obtener_entero('registro_estudiantes.max_mb_csv', 2)
    if tipo == 'propuesta':
        return param_servicios.obtener_entero('propuesta.max_mb_docx', 10)
    return 10


def _guardar_archivo(archivo, plantilla, numero_version):
    """Persiste el archivo en MEDIA_ROOT/documentos/ y devuelve la ruta relativa.

    La carpeta documentos/ es la única que SISTRA-02 sirve al exterior (protección
    agregada en ese PR). La ruta relativa se guarda en `ruta_archivo` para que el
    módulo de propuestas pueda construir la URL de descarga.
    """
    from django.conf import settings

    directorio = os.path.join(settings.MEDIA_ROOT, 'documentos')
    os.makedirs(directorio, exist_ok=True)
    # Nombre único: tipo_plantilla-pk-v{n}-nombre_original
    nombre_seguro = archivo.name.replace(' ', '_')
    nombre = f'{plantilla.tipo}-{plantilla.pk}-v{numero_version}-{nombre_seguro}'
    ruta = os.path.join(directorio, nombre)
    with open(ruta, 'wb') as destino:
        for bloque in archivo.chunks():
            destino.write(bloque)
    # Ruta relativa a MEDIA_ROOT: "documentos/nombre_archivo"
    return os.path.join('documentos', nombre)


class DocumentosView(ParametrizarRequeridoMixin, View):
    """Lista todas las plantillas con su versión vigente."""

    template_name = 'parametrizacion/parametrizacion/documentos.html'

    def get(self, request):
        plantillas = (
            Plantilla.objects.prefetch_related('versiones')
            .order_by('tipo', 'nombre')
        )
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'documentos',
            'plantillas': plantillas,
            'form_plantilla': PlantillaForm(),
        })


class CrearPlantillaView(ParametrizarRequeridoMixin, View):
    """Crea una plantilla nueva (sin archivo inicial)."""

    def post(self, request):
        form = PlantillaForm(request.POST)
        if form.is_valid():
            plantilla = form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Crear plantilla',
                tabla_afectada='plantilla',
                id_registro_afectado=plantilla.pk,
                detalle=f'{plantilla.nombre} ({plantilla.tipo})',
                resultado='Éxito',
            )
            messages.success(request, f'Plantilla «{plantilla.nombre}» creada.')
        else:
            for errores in form.errors.values():
                for error in errores:
                    messages.error(request, error)
        return redirect('parametrizacion:documentos')


class EditarPlantillaView(ParametrizarRequeridoMixin, View):
    """Edita nombre, tipo, descripción y estado de una plantilla."""

    template_name = 'parametrizacion/parametrizacion/documentos_editar.html'

    def get(self, request, pk):
        plantilla = get_object_or_404(Plantilla, pk=pk)
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'documentos',
            'plantilla': plantilla,
            'form': PlantillaForm(instance=plantilla),
        })

    def post(self, request, pk):
        plantilla = get_object_or_404(Plantilla, pk=pk)
        form = PlantillaForm(request.POST, instance=plantilla)
        if form.is_valid():
            form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='Editar plantilla',
                tabla_afectada='plantilla',
                id_registro_afectado=plantilla.pk,
                detalle=f'{plantilla.nombre}',
                resultado='Éxito',
            )
            messages.success(request, f'Plantilla «{plantilla.nombre}» actualizada.')
            return redirect('parametrizacion:documentos')
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'documentos',
            'plantilla': plantilla,
            'form': form,
        })


class SubirVersionView(ParametrizarRequeridoMixin, View):
    """Sube una nueva versión de archivo para una plantilla.
    La versión anterior deja de ser vigente automáticamente.
    """

    template_name = 'parametrizacion/parametrizacion/documentos_version.html'

    def get(self, request, pk):
        plantilla = get_object_or_404(Plantilla, pk=pk)
        return render(request, self.template_name, {
            **contexto_menu(request.user),
            'seccion': 'documentos',
            'plantilla': plantilla,
            'form': VersionPlantillaForm(),
            'versiones': plantilla.versiones.order_by('-numero_version'),
        })

    def post(self, request, pk):
        plantilla = get_object_or_404(Plantilla, pk=pk)
        form = VersionPlantillaForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {
                **contexto_menu(request.user),
                'seccion': 'documentos',
                'plantilla': plantilla,
                'form': form,
                'versiones': plantilla.versiones.order_by('-numero_version'),
            })

        archivo = form.cleaned_data['archivo']

        # Validación de extensión según tipo de plantilla (BRD: configuración por tipo)
        extensiones = _extensiones_para(plantilla.tipo)
        if not any(archivo.name.lower().endswith(ext) for ext in extensiones):
            form.add_error('archivo', f'Para plantillas de tipo «{plantilla.tipo}» solo se permiten: {", ".join(extensiones)}.')
            return render(request, self.template_name, {
                **contexto_menu(request.user),
                'seccion': 'documentos',
                'plantilla': plantilla,
                'form': form,
                'versiones': plantilla.versiones.order_by('-numero_version'),
            })

        # Validación de tamaño según parámetro del sistema
        max_mb = _max_mb_para(plantilla.tipo)
        if archivo.size > max_mb * 1024 * 1024:
            form.add_error('archivo', f'El archivo no puede pesar más de {max_mb} MB.')
            return render(request, self.template_name, {
                **contexto_menu(request.user),
                'seccion': 'documentos',
                'plantilla': plantilla,
                'form': form,
                'versiones': plantilla.versiones.order_by('-numero_version'),
            })

        ultimo = plantilla.versiones.order_by('-numero_version').first()
        numero = (ultimo.numero_version + 1) if ultimo else 1

        try:
            with transaction.atomic():
                # Desactiva versión vigente anterior
                plantilla.versiones.filter(es_vigente=True).update(es_vigente=False)

                ruta = _guardar_archivo(archivo, plantilla, numero)
                version = VersionPlantilla.objects.create(
                    plantilla=plantilla,
                    usuario=request.user,
                    numero_version=numero,
                    nombre_archivo=archivo.name,
                    ruta_archivo=ruta,
                    es_vigente=True,
                )
                Auditoria.objects.create(
                    usuario=request.user,
                    accion='Subir versión de plantilla',
                    tabla_afectada='version_plantilla',
                    id_registro_afectado=version.pk,
                    detalle=f'{plantilla.nombre} v{numero} — {archivo.name}',
                    resultado='Éxito',
                )
        except Exception as error:
            messages.error(request, f'No se pudo guardar el archivo: {error}')
            return redirect('parametrizacion:documentos_version', pk=pk)

        messages.success(
            request,
            f'Versión {numero} de «{plantilla.nombre}» cargada y activada.',
        )
        return redirect('parametrizacion:documentos')


class DescargaPlantillaView(ParametrizarRequeridoMixin, View):
    """Descarga la versión vigente de una plantilla. Solo el Administrador."""

    def get(self, request, pk):
        from django.conf import settings
        plantilla = get_object_or_404(Plantilla, pk=pk)
        version = plantilla.versiones.filter(es_vigente=True).first()
        if not version:
            messages.error(request, 'Esta plantilla no tiene versión vigente.')
            return redirect('parametrizacion:documentos')
        ruta = os.path.join(settings.MEDIA_ROOT, version.ruta_archivo)
        if not os.path.exists(ruta):
            messages.error(request, 'El archivo no se encontró en el servidor.')
            return redirect('parametrizacion:documentos')
        return FileResponse(
            open(ruta, 'rb'), as_attachment=True, filename=version.nombre_archivo
        )


class DescargaPlantillaCsvEstudiantesView(PermissionRequiredMixin, View):
    """Descarga la plantilla CSV de estudiantes.

    Accesible a quien tenga `estudiante.cargar_csv` (Director y ADMO).
    Si no hay versión vigente cargada, devuelve un CSV básico con las
    columnas acordadas con SISTRA-10 (nombre, cedula, correo, carrera).
    URL: parametrizacion:plantilla_csv_estudiantes
    """
    permission_required = 'estudiante.cargar_csv'

    def get(self, request):
        from django.conf import settings
        plantilla = Plantilla.objects.filter(tipo='csv', estado='Activo').first()
        if plantilla:
            version = plantilla.versiones.filter(es_vigente=True).first()
            if version:
                ruta = os.path.join(settings.MEDIA_ROOT, version.ruta_archivo)
                if os.path.exists(ruta):
                    return FileResponse(
                        open(ruta, 'rb'),
                        as_attachment=True,
                        filename=version.nombre_archivo,
                    )

        # Fallback: CSV básico con las columnas del BRD
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="plantilla_estudiantes.csv"'
        writer = csv.writer(response)
        writer.writerow(['nombre', 'cedula', 'correo', 'carrera'])
        return response
