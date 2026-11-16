"""SISTRA-11 · Parametrización: formularios de estados del proceso (actividades y tipos de rechazo)."""

from django import forms

from apps.usuarios.models import Estado

from ..models import Actividad, TipoRechazo


class ActividadForm(forms.ModelForm):
    """Creación y edición de etapas (actividades) del proceso de Trabajo Social."""

    obligatoria = forms.BooleanField(
        required=False,
        initial=True,
        label='Obligatoria para el estudiante',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = Actividad
        fields = ['nombre', 'descripcion', 'orden', 'obligatoria', 'estado']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control sis-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control sis-input', 'rows': 2}),
            'orden': forms.NumberInput(attrs={'class': 'form-control sis-input', 'min': 1}),
            'estado': forms.Select(attrs={'class': 'form-select sis-input'}, choices=Estado.choices),
        }
        labels = {
            'nombre': 'Nombre de la etapa',
            'descripcion': 'Descripción',
            'orden': 'Orden en el proceso',
            'estado': 'Estado',
        }

    def clean_orden(self):
        orden = self.cleaned_data.get('orden')
        if orden is not None and orden < 1:
            raise forms.ValidationError('El orden debe ser un número entero mayor a 0.')
        queryset = Actividad.objects.filter(orden=orden)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(f'Ya existe una etapa con el orden {orden}.')
        return orden


class TipoRechazoForm(forms.ModelForm):
    """Creación y edición de causales de rechazo de propuestas e informes."""

    class Meta:
        model = TipoRechazo
        fields = ['nombre', 'descripcion', 'estado']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control sis-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control sis-input', 'rows': 2}),
            'estado': forms.Select(attrs={'class': 'form-select sis-input'}, choices=Estado.choices),
        }
        labels = {
            'nombre': 'Motivo o causal de rechazo',
            'descripcion': 'Descripción o justificación',
            'estado': 'Estado',
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get('nombre') or '').strip()
        if not nombre:
            raise forms.ValidationError('El nombre no puede estar vacío.')
        queryset = TipoRechazo.objects.filter(nombre__iexact=nombre)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError(f'Ya existe un tipo de rechazo con el nombre «{nombre}».')
        return nombre
