"""SISTRA-12 · Reportes: formularios.

Solo el responsable de este requisito edita este archivo.
"""

"""SISTRA-12 · Reportes: formularios."""

from django import forms
from django.utils import timezone


# Mensajes oficiales del BRD SISTRA-12
MSG_REP_01 = 'Debe diligenciar las fechas obligatorias para generar el reporte.'
MSG_REP_02 = 'No se encontraron registros para el rango de fechas seleccionado.'
MSG_REP_03 = (
    'La fecha desde no puede ser posterior a hoy ni la fecha hasta '
    'anterior a la fecha desde.'
)
MSG_REP_04 = (
    'Ocurrió un error al generar el reporte. Por favor, intente nuevamente.'
)
MSG_REP_05 = 'Generando reporte…'


class FormularioReporte(forms.Form):
    """Valida el rango de fechas para generar el reporte."""

    filterDateStart = forms.DateField(
        label='Fecha desde',
        required=True,
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control'},
            format='%Y-%m-%d',
        ),
        error_messages={'required': MSG_REP_01},
    )

    filterDateEnd = forms.DateField(
        label='Fecha hasta',
        required=True,
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control'},
            format='%Y-%m-%d',
        ),
        error_messages={'required': MSG_REP_01},
    )

    def clean(self):
        cleaned_data = super().clean()

        fecha_desde = cleaned_data.get('filterDateStart')
        fecha_hasta = cleaned_data.get('filterDateEnd')
        hoy = timezone.localdate()

        if fecha_desde and fecha_desde > hoy:
            self.add_error('filterDateStart', MSG_REP_03)

        if fecha_desde and fecha_hasta and fecha_hasta < fecha_desde:
            self.add_error('filterDateEnd', MSG_REP_03)

        return cleaned_data
