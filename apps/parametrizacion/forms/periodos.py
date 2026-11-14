"""SISTRA-11 · Periodo académico: formulario."""
import re

from django import forms

from ..models import EstadoPeriodo, PeriodoAcademico

FORMATO_NOMBRE = re.compile(r'\d{4}-\d')


def _fecha():
    return forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d')


class PeriodoForm(forms.Form):
    CAMPOS = (
        'nombre', 'fecha_inicio', 'fecha_fin',
        'fecha_cierre_propuesta', 'fecha_cierre_informe', 'estado',
    )

    nombre = forms.CharField(
        label='Periodo', max_length=20, help_text='Formato aaaa-n, por ejemplo 2026-2.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )
    fecha_inicio = forms.DateField(label='Inicio del periodo', widget=_fecha())
    fecha_fin = forms.DateField(label='Fin del periodo', widget=_fecha())
    fecha_cierre_propuesta = forms.DateField(label='Cierre de propuesta', widget=_fecha())
    fecha_cierre_informe = forms.DateField(label='Cierre de informe', widget=_fecha())
    estado = forms.ChoiceField(
        label='Estado', choices=EstadoPeriodo.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, periodo=None, **kwargs):
        self.periodo = periodo
        if periodo is not None and not args and 'initial' not in kwargs:
            kwargs['initial'] = {campo: getattr(periodo, campo) for campo in self.CAMPOS}
        super().__init__(*args, **kwargs)

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        if not FORMATO_NOMBRE.fullmatch(nombre):
            raise forms.ValidationError('Use el formato aaaa-n, por ejemplo 2026-2.')
        repetidos = PeriodoAcademico.objects.filter(nombre__iexact=nombre)
        if self.periodo is not None:
            repetidos = repetidos.exclude(pk=self.periodo.pk)
        if repetidos.exists():
            raise forms.ValidationError('Ya existe un periodo con ese nombre.')
        return nombre

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get('fecha_inicio'), datos.get('fecha_fin')
        propuesta, informe = datos.get('fecha_cierre_propuesta'), datos.get('fecha_cierre_informe')
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', 'El fin del periodo no puede ser anterior al inicio.')
        if inicio and fin and propuesta and not (inicio <= propuesta <= fin):
            self.add_error(
                'fecha_cierre_propuesta', 'El cierre de la propuesta debe estar dentro del periodo.'
            )
        if propuesta and informe and informe <= propuesta:
            self.add_error(
                'fecha_cierre_informe',
                'El cierre del informe debe ser posterior al cierre de la propuesta.',
            )
        return datos

    def full_clean(self):
        super().full_clean()
        for nombre_campo in self.errors:
            if nombre_campo in self.fields:
                widget = self.fields[nombre_campo].widget
                widget.attrs['class'] = widget.attrs.get('class', '') + ' is-invalid'
                widget.attrs['aria-invalid'] = 'true'