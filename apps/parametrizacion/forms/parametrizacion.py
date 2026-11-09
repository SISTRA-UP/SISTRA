"""SISTRA-11 · Parametrización: formularios."""
from django import forms
from django.core.validators import FileExtensionValidator

from ..models import Carrera

_TEXTO = {'class': 'form-control sis-input', 'autocomplete': 'off'}


class CrearUsuarioForm(forms.Form):
    """Datos de un estudiante. Las reglas de negocio viven en
    `apps.usuarios.servicios`; aquí solo se valida la forma."""

    nombre = forms.CharField(label='Nombre', max_length=100, widget=forms.TextInput(attrs=_TEXTO))
    apellido = forms.CharField(label='Apellido', max_length=100, widget=forms.TextInput(attrs=_TEXTO))
    cedula = forms.CharField(
        label='Cédula (CC)', max_length=15, help_text='Solo números.',
        widget=forms.TextInput(attrs={**_TEXTO, 'inputmode': 'numeric'}),
    )
    correo = forms.EmailField(
        label='Correo institucional', max_length=254,
        help_text='Debe terminar en @unipamplona.edu.co.',
        widget=forms.EmailInput(attrs=_TEXTO),
    )
    telefono = forms.CharField(
        label='Teléfono', max_length=20, required=False,
        widget=forms.TextInput(attrs={**_TEXTO, 'inputmode': 'tel'}),
    )

    def full_clean(self):
        super().full_clean()
        for nombre_campo in self.errors:
            if nombre_campo in self.fields:
                widget = self.fields[nombre_campo].widget
                widget.attrs['class'] = widget.attrs.get('class', '') + ' is-invalid'
                widget.attrs['aria-invalid'] = 'true'


class CrearDirectorForm(CrearUsuarioForm):
    """Alta de un Director: mismos datos personales más su carrera."""

    carrera = forms.ModelChoiceField(
        label='Carrera', empty_label='Seleccione…',
        queryset=Carrera.objects.filter(estado='Activo').order_by('nombre'),
        help_text='Una carrera solo puede tener un director activo.',
        widget=forms.Select(attrs={'class': 'form-select sis-input'}),
    )


class CargaMasivaForm(forms.Form):
    archivo = forms.FileField(
        label='Archivo CSV',
        validators=[FileExtensionValidator(['csv'], message='El archivo debe ser .csv.')],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control sis-input', 'accept': '.csv'}),
    )