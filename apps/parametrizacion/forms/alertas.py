"""SISTRA-11 · Alertas y plazos: formulario."""
from django import forms
from django.core.validators import URLValidator

MENSAJE_ENTERO = 'Ingrese un número entero mayor que cero.'


def _entero(etiqueta, ayuda='', obligatorio=True, maximo=365):
    return forms.IntegerField(
        label=etiqueta, help_text=ayuda, required=obligatorio, min_value=1, max_value=maximo,
        error_messages={
            'required': 'Este campo es obligatorio.',
            'invalid': MENSAJE_ENTERO,
            'min_value': MENSAJE_ENTERO,
            'max_value': f'Ingrese un valor entre 1 y {maximo}.',
        },
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
    )


class AlertasForm(forms.Form):
    verde_hasta_dias = _entero(
        'Verde hasta (días)', 'Días calendario en revisión con semáforo verde.'
    )
    amarillo_hasta_dias = _entero(
        'Amarillo hasta (días)', 'Después de este límite el semáforo pasa a rojo.'
    )
    frecuencia_recordatorio_dias = _entero(
        'Recordar al estudiante cada (días)',
        'Aviso interno de SISTRA mientras la propuesta esté aprobada y no declarada como «Subido en UP».',
    )
    dias_archivado_propuesta = _entero(
        'Archivar propuestas rechazadas a los (días)', 'Déjelo vacío si aún no está definido.',
        obligatorio=False, maximo=3650,
    )
    dias_archivado_informe = _entero(
        'Archivar informes rechazados a los (días)', 'Déjelo vacío si aún no está definido.',
        obligatorio=False, maximo=3650,
    )
    url_up = forms.CharField(
        label='Dirección de la plataforma UP', required=False, max_length=300,
        help_text='Debe empezar por https://. Déjela vacía si aún no se conoce.',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
    )

    def clean_url_up(self):
        url = (self.cleaned_data.get('url_up') or '').strip()
        if url:
            if not url.lower().startswith('https://'):
                raise forms.ValidationError('La dirección debe empezar por https://')
            try:
                URLValidator(schemes=['https'])(url)
            except forms.ValidationError:
                raise forms.ValidationError('Ingrese una dirección válida.') from None
        return url

    def clean(self):
        datos = super().clean()
        verde, amarillo = datos.get('verde_hasta_dias'), datos.get('amarillo_hasta_dias')
        if verde and amarillo and amarillo <= verde:
            self.add_error(
                'amarillo_hasta_dias', 'El límite del amarillo debe ser mayor que el del verde.'
            )
        return datos

    def full_clean(self):
        super().full_clean()
        for nombre_campo in self.errors:
            if nombre_campo in self.fields:
                widget = self.fields[nombre_campo].widget
                widget.attrs['class'] = widget.attrs.get('class', '') + ' is-invalid'
                widget.attrs['aria-invalid'] = 'true'