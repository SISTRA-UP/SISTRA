"""Formularios de facultades y carreras (SISTRA-11)."""

from django import forms
from django.db.models import Q

from apps.usuarios.models import Estado

from ..models import Carrera, Facultad


class FacultadForm(forms.ModelForm):
    class Meta:
        model = Facultad
        fields = ['nombre', 'descripcion', 'estado']
        labels = {
            'nombre': 'Nombre de la facultad',
            'descripcion': 'Descripción',
            'estado': 'Estado',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        existentes = Facultad.objects.filter(nombre__iexact=nombre)
        if self.instance.pk:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise forms.ValidationError('Ya existe una facultad con ese nombre.')
        return nombre


class CarreraForm(forms.ModelForm):
    class Meta:
        model = Carrera
        fields = ['nombre', 'codigo', 'facultad', 'estado']
        labels = {
            'nombre': 'Nombre de la carrera',
            'codigo': 'Código',
            'facultad': 'Facultad',
            'estado': 'Estado',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'facultad': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        facultades = Facultad.objects.filter(estado=Estado.ACTIVO)
        if self.instance.pk and self.instance.facultad_id:
            facultades = Facultad.objects.filter(
                Q(estado=Estado.ACTIVO) | Q(pk=self.instance.facultad_id)
            )
        self.fields['facultad'].queryset = facultades.order_by('nombre')

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        existentes = Carrera.objects.filter(codigo__iexact=codigo)
        if self.instance.pk:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise forms.ValidationError('Ya existe una carrera con ese código.')
        return codigo

    def clean(self):
        datos = super().clean()
        nombre, facultad = datos.get('nombre'), datos.get('facultad')
        if nombre and facultad:
            existentes = Carrera.objects.filter(nombre__iexact=nombre, facultad=facultad)
            if self.instance.pk:
                existentes = existentes.exclude(pk=self.instance.pk)
            if existentes.exists():
                self.add_error('nombre', 'Ya existe una carrera con ese nombre en la facultad seleccionada.')
        return datos
