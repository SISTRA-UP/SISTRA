"""SISTRA-07 · Formulario para decisiones masivas."""

from django import forms

from apps.informes.forms.aprobacion import DecisionInformeForm
from apps.informes.models import Informe
from apps.propuestas.models import EstadoTramite


class DecisionMasivaInformeForm(DecisionInformeForm):
    """Valida la decisión y los informes autorizados seleccionados.

    No guarda cambios. La vista deberá volver a comprobar los permisos,
    los estados y los bloqueos dentro de la transacción de guardado.
    """

    informes = forms.ModelMultipleChoiceField(
        label="Informes seleccionados",
        queryset=Informe.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple(),
        error_messages={
            "required": "Selecciona al menos un informe.",
            "invalid_choice": (
                "La selección contiene un informe no disponible "
                "para esta operación. Actualiza la pantalla."
            ),
            "invalid_pk_value": (
                "La selección contiene un identificador no válido."
            ),
        },
    )

    def __init__(self, *args, informes_permitidos=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["nuevo_estado"].choices = [
            ("", "Selecciona una decisión"),
            (EstadoTramite.APROBADO, "Aprobar seleccionados"),
            (EstadoTramite.RECHAZADO, "Rechazar seleccionados"),
        ]

        # Sin una consulta autorizada, no acepta ningún informe.
        if informes_permitidos is not None:
            self.fields["informes"].queryset = informes_permitidos