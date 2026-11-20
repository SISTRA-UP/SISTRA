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


class DocumentosParametrosForm(forms.Form):
    """Límites de carga para documentos y formatos administrados en SISTRA-11."""

    max_mb_docx = forms.IntegerField(
        label='Tamaño máximo de propuesta (.docx)', min_value=1, max_value=50,
        error_messages={
            'required': 'Este campo es obligatorio.',
            'invalid': 'Ingrese un número entero entre 1 y 50.',
            'min_value': 'El valor debe ser mayor que 0.',
            'max_value': 'El valor máximo permitido es 50.',
        },
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 50}),
    )
    max_mb_csv = forms.IntegerField(
        label='Tamaño máximo de estudiantes (.csv)', min_value=1, max_value=50,
        error_messages={
            'required': 'Este campo es obligatorio.',
            'invalid': 'Ingrese un número entero entre 1 y 50.',
            'min_value': 'El valor debe ser mayor que 0.',
            'max_value': 'El valor máximo permitido es 50.',
        },
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 50}),
    )
    # PRO-16. Opcional: si no llega en el formulario se conserva el valor vigente.
    max_mb_documentos_extra = forms.IntegerField(
        label='Tamaño máximo de documentos extra (.pdf)', min_value=1, max_value=50, required=False,
        error_messages={
            'required': 'Este campo es obligatorio.',
            'invalid': 'Ingrese un número entero entre 1 y 50.',
            'min_value': 'El valor debe ser mayor que 0.',
            'max_value': 'El valor máximo permitido es 50.',
        },
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 50}),
    )
    maximo_filas_csv = forms.IntegerField(
        label='Máximo de filas por CSV de estudiantes', min_value=1, max_value=5000,
        error_messages={
            'required': 'Este campo es obligatorio.',
            'invalid': 'Ingrese un número entero entre 1 y 5000.',
            'min_value': 'El valor debe ser mayor que 0.',
            'max_value': 'El valor máximo permitido es 5000.',
        },
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 5000}),
    )


class PlantillaForm(forms.ModelForm):
    """Crear o editar una plantilla (sin archivo — el archivo va en VersionPlantillaForm)."""

    tipo = forms.ChoiceField(
        choices=TIPOS_PLANTILLA,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    estado = forms.ChoiceField(
        choices=ESTADOS_PLANTILLA,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Plantilla
        fields = ['nombre', 'tipo', 'descripcion', 'estado']
        widgets = {
            'nombre':      forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'nombre':      'Nombre',
            'tipo':        'Tipo de documento',
            'descripcion': 'Descripción',
            'estado':      'Estado',
        }

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get('tipo')
        estado = cleaned_data.get('estado')
        if tipo and estado == 'Activo':
            existentes = Plantilla.objects.filter(tipo=tipo, estado='Activo')
            if self.instance.pk:
                existentes = existentes.exclude(pk=self.instance.pk)
            if existentes.exists():
                self.add_error('tipo', 'Ya existe una plantilla activa de este tipo.')
        return cleaned_data


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
