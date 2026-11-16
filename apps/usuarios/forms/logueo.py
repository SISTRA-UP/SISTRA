"""SISTRA-13 · Formularios del inicio y recuperación de sesión."""

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


DOMINIO_INSTITUCIONAL = 'unipamplona.edu.co'


class CorreoInstitucionalForm(forms.Form):
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
            }
        ),
    )

    def clean_correo(self):
        correo = self.cleaned_data['correo'].strip().lower()
        partes = correo.rsplit('@', 1)
        if len(partes) != 2 or not partes[0] or partes[1] != DOMINIO_INSTITUCIONAL:
            raise ValidationError(
                'Usa tu correo institucional con el dominio @unipamplona.edu.co.'
            )
        return correo


class LoginForm(CorreoInstitucionalForm):
    contrasena = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control form-control-lg',
                'autocomplete': 'current-password',
                'placeholder': 'Escribe tu contraseña',
                'data-password-input': 'true',
            }
        ),
    )


class RecuperarContrasenaForm(CorreoInstitucionalForm):
    pass


class CambiarContrasenaForm(forms.Form):
    contrasena_actual = forms.CharField(
        label='Contraseña actual',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'current-password',
                'data-password-input': 'true',
            }
        ),
    )
    contrasena_nueva = forms.CharField(
        label='Nueva contraseña',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'new-password',
                'data-password-input': 'true',
                'data-password-strength': 'true',
            }
        ),
    )
    confirmar_contrasena = forms.CharField(
        label='Confirmar contraseña',
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                'class': 'form-control',
                'autocomplete': 'new-password',
                'data-password-input': 'true',
            }
        ),
    )

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario

    def clean(self):
        datos = super().clean()
        actual = datos.get('contrasena_actual')
        nueva = datos.get('contrasena_nueva')
        confirmacion = datos.get('confirmar_contrasena')

        if actual and not self.usuario.check_password(actual):
            self.add_error('contrasena_actual', 'La contraseña actual no es correcta.')

        if nueva and actual and nueva == actual:
            self.add_error(
                'contrasena_nueva',
                'La nueva contraseña debe ser diferente de la contraseña temporal actual.',
            )

        if nueva and confirmacion and nueva != confirmacion:
            self.add_error(
                'confirmar_contrasena',
                'La nueva contraseña no coincide con la confirmación.',
            )

        if nueva:
            try:
                validate_password(nueva, self.usuario)
            except ValidationError as error:
                self.add_error('contrasena_nueva', error)

        return datos
