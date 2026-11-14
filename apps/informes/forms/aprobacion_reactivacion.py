"""SISTRA-07 · Validaciones para reactivar informes."""

from django import forms
from apps.propuestas.forms.aprobacion import LONGITUD_MAXIMA_TEXTO
from django.core.exceptions import ValidationError

from apps.informes.models import Informe
from apps.propuestas.models import EstadoTramite


class ReactivacionInformeForm(forms.Form):
    """Exige un motivo y la versión del informe que se está revisando."""

    motivo = forms.CharField(
        max_length=LONGITUD_MAXIMA_TEXTO,
        label="Motivo de la reactivación",
        required=True,
        strip=True,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": (
                    "Explica por qué debe reactivarse el informe rechazado."
                ),
            }
        ),
        error_messages={
            "required": "Escribe el motivo de la reactivación.",
        },
    )

    fecha_actualizacion = forms.DateTimeField(
        required=True,
        widget=forms.HiddenInput(),
        error_messages={
            "required": (
                "Actualiza la pantalla antes de reactivar el informe."
            ),
            "invalid": (
                "La versión del informe no es válida. "
                "Actualiza la pantalla."
            ),
        },
    )


def validar_condiciones_reactivacion(informe):
    """Comprueba las condiciones del informe sin modificarlo.

    Esta función no comprueba permisos del usuario.
    La futura vista deberá verificar al Director y repetir estas
    validaciones dentro de la transacción que guarde la reactivación.
    """

    if informe.archivado:
        raise ValidationError(
            "No se puede reactivar un informe archivado.",
            code="informe_archivado",
        )

    if informe.estado != EstadoTramite.RECHAZADO:
        raise ValidationError(
            "Solo se pueden reactivar informes rechazados.",
            code="estado_no_rechazado",
        )

    existe_otro_activo = (
        Informe.objects.filter(
            propuesta_id=informe.propuesta_id,
            archivado=False,
        )
        .exclude(pk=informe.pk)
        .exclude(estado=EstadoTramite.RECHAZADO)
        .exists()
    )

    if existe_otro_activo:
        raise ValidationError(
            "No se puede reactivar: ya existe otro informe activo "
            "para la misma propuesta.",
            code="otro_informe_activo",
        )
