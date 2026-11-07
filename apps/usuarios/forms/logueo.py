"""SISTRA-13 · Formulario de inicio de sesión para estudiantes."""

from django import forms
from django.core.exceptions import ValidationError


DOMINIO_INSTITUCIONAL = 'unipamplona.edu.co'


class LoginEstudianteForm(forms.Form):
    correo = forms.EmailField(
        label='Correo institucional',
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                'class': 'form-control form-control-lg',
                'autocomplete': 'username',
                'placeholder': 'nombre@unipamplona.edu.co',
                'autocapitalize': 'none',
                'spellcheck': 'false',
                'autofocus': True,
            }
        ),
    )
    contrasena = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control form-control-lg',
                'autocomplete': 'current-password',
                'placeholder': 'Escribe tu contraseña',
            }
        ),
    )

    def clean_correo(self):
        """Normaliza el correo y solo acepta el dominio institucional exacto."""
        correo = self.cleaned_data['correo'].strip().lower()
        partes = correo.split('@')

        if len(partes) != 2 or partes[1] != DOMINIO_INSTITUCIONAL:
            raise ValidationError(
                'Usa tu correo institucional con el dominio '
                '@unipamplona.edu.co.'
            )

        return correo
