"""Formulario de montaje de informe (SISTRA-06).

Validaciones:
- Cada campo: mínimo 50 y máximo 1000 caracteres al enviar.
- Guardar borrador: no exige mínimo, solo máximo.
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.informes.models import Informe


# ─── Mensajes del BRD (tabla de mensajes del SISTRA-06) ───
MSG_06_01 = 'Tu informe se guardó como borrador.'
MSG_06_02 = 'Tu informe se envió y quedó en revisión.'
MSG_06_03 = 'Completa este campo (mínimo 50 caracteres).'
MSG_06_04 = 'Este informe está en revisión y no se puede modificar.'
MSG_06_05 = (
    'Podrás montar tu informe cuando tu Director marque tu propuesta '
    'como Aprobado en UP.'
)

MINIMO_CARACTERES = 50
MAXIMO_CARACTERES = 1000


class InformeForm(forms.ModelForm):
    """Formulario para diligenciar el informe de Trabajo Social."""

    # ⬅ Sobrescribir los campos con max_length explícito
    resultados = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Describa los resultados obtenidos...',
                'maxlength': MAXIMO_CARACTERES,
            }
        ),
        max_length=MAXIMO_CARACTERES,
        required=False,
        error_messages={'max_length': f'Máximo {MAXIMO_CARACTERES} caracteres.'},
    )
    conclusiones = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Escriba las conclusiones...',
                'maxlength': MAXIMO_CARACTERES,
            }
        ),
        max_length=MAXIMO_CARACTERES,
        required=False,
        error_messages={'max_length': f'Máximo {MAXIMO_CARACTERES} caracteres.'},
    )
    recomendaciones = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': 'Incluya recomendaciones...',
                'maxlength': MAXIMO_CARACTERES,
            }
        ),
        max_length=MAXIMO_CARACTERES,
        required=False,
        error_messages={'max_length': f'Máximo {MAXIMO_CARACTERES} caracteres.'},
    )

    class Meta:
        model = Informe
        fields = ['resultados', 'conclusiones', 'recomendaciones']

    def __init__(self, *args, accion=None, **kwargs):
        """Recibe la acción ('guardar_borrador' o 'enviar') para validar mínimo."""
        super().__init__(*args, **kwargs)
        self.accion = accion

    def clean(self):
        """Valida mínimo 50 caracteres SOLO cuando la acción es 'enviar'."""
        cleaned_data = super().clean()

        if self.accion == 'enviar':
            for campo in ['resultados', 'conclusiones', 'recomendaciones']:
                valor = (cleaned_data.get(campo) or '').strip()
                if len(valor) < MINIMO_CARACTERES:
                    self.add_error(campo, MSG_06_03)

        return cleaned_data