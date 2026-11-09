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
    """Subir una nueva versión de archivo para una plantilla existente."""

    archivo = forms.FileField(
        label='Archivo',
        help_text='Formatos permitidos: .docx, .xlsx, .csv, .pdf.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )

    EXTENSIONES = ('.docx', '.xlsx', '.csv', '.pdf')

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        nombre = archivo.name.lower()
        if not any(nombre.endswith(ext) for ext in self.EXTENSIONES):
            raise forms.ValidationError(
                f'Solo se permiten: {", ".join(self.EXTENSIONES)}.'
            )
        if archivo.size > 10 * 1024 * 1024:
            raise forms.ValidationError('El archivo no puede pesar más de 10 MB.')
        return archivo
