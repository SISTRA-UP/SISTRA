"""SISTRA-11 · Parametrización: formularios de documentos y formatos."""

from django import forms

from ..models import Plantilla, VersionPlantilla

TIPOS_PLANTILLA = [
    ('propuesta', 'Propuesta de Trabajo Social'),
    ('informe',   'Informe de Trabajo Social'),
    ('csv',       'Plantilla CSV de estudiantes'),
    ('otro',      'Otro'),
]

ESTADOS_PLANTILLA = [
    ('Activo',   'Activo'),
    ('Inactivo', 'Inactivo'),
]


class PlantillaForm(forms.ModelForm):
    """Crear o editar una plantilla (sin archivo — el archivo va en VersionPlantillaForm)."""

    class Meta:
        model = Plantilla
        fields = ['nombre', 'tipo', 'descripcion', 'estado']
        widgets = {
            'nombre':      forms.TextInput(attrs={'class': 'form-control'}),
            'tipo':        forms.Select(attrs={'class': 'form-select'},
                                        choices=TIPOS_PLANTILLA),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'estado':      forms.Select(attrs={'class': 'form-select'},
                                        choices=ESTADOS_PLANTILLA),
        }
        labels = {
            'nombre':      'Nombre',
            'tipo':        'Tipo de documento',
            'descripcion': 'Descripción',
            'estado':      'Estado',
        }


class VersionPlantillaForm(forms.Form):
    """Subir una nueva versión de archivo para una plantilla existente.

    La validación de extensión y tamaño se hace en la vista (SubirVersionView)
    porque depende del tipo de plantilla y del parámetro del sistema.
    """

    archivo = forms.FileField(
        label='Archivo',
        help_text='El formato y tamaño permitidos dependen del tipo de plantilla.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )
