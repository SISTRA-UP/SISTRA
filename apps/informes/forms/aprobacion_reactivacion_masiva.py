"""SISTRA-07 · Formulario de reactivación masiva."""

from django import forms
from apps.propuestas.forms.aprobacion import LONGITUD_MAXIMA_TEXTO

from apps.informes.models import Informe


class ReactivacionMasivaInformeForm(forms.Form):
    motivo = forms.CharField(
        max_length=LONGITUD_MAXIMA_TEXTO,
        required=True,
        strip=True,
        error_messages={
            "required": "Escribe el motivo de la reactivación.",
        },
    )

    informes = forms.ModelMultipleChoiceField(
        queryset=Informe.objects.none(),
        required=True,
        error_messages={
            "required": "Selecciona al menos un informe.",
            "invalid_choice": (
                "La selección contiene un informe no disponible."
            ),
        },
    )

    versiones = forms.JSONField(
        required=True,
        error_messages={
            "required": "Actualiza la pantalla antes de confirmar.",
            "invalid": "Las versiones de los informes no son válidas.",
        },
    )

    def __init__(self, *args, informes_permitidos=None, **kwargs):
        super().__init__(*args, **kwargs)

        if informes_permitidos is not None:
            self.fields["informes"].queryset = informes_permitidos

    def clean_versiones(self):
        versiones = self.cleaned_data["versiones"]

        if not isinstance(versiones, dict):
            raise forms.ValidationError(
                "Las versiones deben identificar cada informe."
            )

        if not all(
            isinstance(valor, str) and valor.strip()
            for valor in versiones.values()
        ):
            raise forms.ValidationError(
                "Las fechas de los informes no son válidas."
            )

        return versiones

    def clean(self):
        datos = super().clean()

        informes = datos.get("informes")
        versiones = datos.get("versiones")

        if informes is not None and isinstance(versiones, dict):
            ids = {str(informe.pk) for informe in informes}

            if set(versiones) != ids:
                self.add_error(
                    "versiones",
                    "Las versiones no coinciden con la selección.",
                )

        return datos
