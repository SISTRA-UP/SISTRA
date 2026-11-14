"""SISTRA-07 · Formularios para la aprobación de informes."""

from django import forms
from apps.propuestas.forms.aprobacion import LONGITUD_MAXIMA_TEXTO

from apps.parametrizacion.models import TipoRechazo
from apps.propuestas.models import EstadoTramite
from apps.usuarios.models import Estado


class DecisionInformeForm(forms.Form):
    """Valida los datos enviados al decidir sobre un informe."""

    nuevo_estado = forms.ChoiceField(
        label="Decisión",
        choices=[
            ("", "Selecciona una decisión"),
            (EstadoTramite.APROBADO, "Aprobado"),
            (
                EstadoTramite.REQUIERE_MODIFICACION,
                "Requiere modificación",
            ),
            (EstadoTramite.RECHAZADO, "Rechazado"),
        ],
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
        error_messages={
            "required": "Selecciona una decisión.",
            "invalid_choice": "La decisión seleccionada no es válida.",
        },
    )

    tipo_rechazo = forms.ModelChoiceField(
        label="Tipo de rechazo",
        queryset=TipoRechazo.objects.none(),
        required=False,
        empty_label="Selecciona un tipo de rechazo",
        widget=forms.Select(
            attrs={"class": "form-select"}
        ),
        error_messages={
            "invalid_choice": "Selecciona un tipo de rechazo activo.",
        },
    )

    observacion = forms.CharField(
        max_length=LONGITUD_MAXIMA_TEXTO,
        label="Observación",
        required=False,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Escribe la observación para el estudiante.",
            }
        ),
    )

    justificacion = forms.CharField(
        label="Justificación interna del cambio",
        required=False, strip=True, max_length=LONGITUD_MAXIMA_TEXTO,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["tipo_rechazo"].queryset = (
            TipoRechazo.objects.filter(
                estado=Estado.ACTIVO,
            ).order_by("nombre")
        )

    def clean(self):
        datos = super().clean()

        decision = datos.get("nuevo_estado")
        observacion = datos.get("observacion")
        tipo_rechazo = datos.get("tipo_rechazo")

        exige_observacion = decision in (
            EstadoTramite.REQUIERE_MODIFICACION,
            EstadoTramite.RECHAZADO,
        )

        if exige_observacion and not observacion and "observacion" not in self.errors:
            self.add_error(
                "observacion",
                "Escribe una observación para explicar la decisión.",
            )

        if decision == EstadoTramite.RECHAZADO:
            if (
                not tipo_rechazo
                and "tipo_rechazo" not in self.errors
            ):
                self.add_error(
                    "tipo_rechazo",
                    "Selecciona el tipo de rechazo.",
                )
        else:
            # Las decisiones distintas de rechazo no guardan una causal.
            datos["tipo_rechazo"] = None

        return datos
