"""SISTRA-05 · Notificación de cargue UP – Director: formularios.

Solo el responsable de este requisito edita este archivo.
"""

from django import forms

from apps.cargue_up.models import EstadoVerificacion


class DecisionPropuestaForm(forms.Form):
    resultado = forms.ChoiceField(
        choices=[
            (EstadoVerificacion.APROBADO_EN_UP, 'Aprobado en UP'),
            (EstadoVerificacion.RECHAZADO_EN_UP, 'Rechazado en UP'),
        ],
        widget=forms.HiddenInput(),
    )
    observacion = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'Observaciones para el estudiante',
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        resultado = cleaned_data.get('resultado')
        observacion = cleaned_data.get('observacion', '').strip()

        if resultado == EstadoVerificacion.RECHAZADO_EN_UP and not observacion:
            self.add_error(
                'observacion',
                'Debes indicar el motivo del rechazo.',
            )

        cleaned_data['observacion'] = observacion
        return cleaned_data


class CorreccionPropuestaForm(forms.Form):
    resultado = forms.ChoiceField(
        choices=[
            (EstadoVerificacion.APROBADO_EN_UP, 'Aprobado en UP'),
            (EstadoVerificacion.RECHAZADO_EN_UP, 'Rechazado en UP'),
        ],
    )
    motivo = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Explica por qué se corrige la verificación',
        }),
    )
    observacion = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Observación para el estudiante',
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        resultado = cleaned_data.get('resultado')
        motivo = cleaned_data.get('motivo', '').strip()
        observacion = cleaned_data.get('observacion', '').strip()

        if not motivo:
            self.add_error('motivo', 'El motivo de corrección es obligatorio.')

        if resultado == EstadoVerificacion.RECHAZADO_EN_UP and not observacion:
            self.add_error(
                'observacion',
                'Debes indicar la observación del rechazo.',
            )

        cleaned_data['motivo'] = motivo
        cleaned_data['observacion'] = observacion
        return cleaned_data
