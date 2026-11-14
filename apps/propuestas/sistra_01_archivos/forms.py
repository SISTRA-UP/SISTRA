"""
forms.py — Formularios del módulo.
"""
from django import forms
from django.core.exceptions import ValidationError

from .models import CAMPOS_OBLIGATORIOS, PropuestaTrabajoSocial


class PropuestaForm(forms.ModelForm):
    """
    - Ningún campo es `required` a nivel HTML/Django: un borrador puede guardarse incompleto.
    - Si `accion == "enviar"`, se exigen todos los CAMPOS_OBLIGATORIOS y un Director asignado.
    - Si la propuesta está bloqueada (EN_REVISION / APROBADO) todos los campos quedan `disabled`
      (Django ignora el POST de campos disabled, así que no se pueden alterar manipulando el HTML).
    """

    class Meta:
        model = PropuestaTrabajoSocial
        fields = list(CAMPOS_OBLIGATORIOS)
        widgets = {
            "poblacion_beneficiada": forms.Textarea(attrs={"rows": 3}),
            "impacto_social": forms.Textarea(attrs={"rows": 4}),
            "descripcion_problema": forms.Textarea(attrs={"rows": 5}),
            "justificacion": forms.Textarea(attrs={"rows": 5}),
            "objetivo_general": forms.Textarea(attrs={"rows": 3}),
            "objetivos_especificos": forms.Textarea(attrs={"rows": 5}),
            "metodologia": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, accion: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.accion = accion
        self.bloqueado = bool(self.instance.pk) and not self.instance.es_editable

        for nombre, campo in self.fields.items():
            campo.required = False
            campo.es_obligatorio = nombre in CAMPOS_OBLIGATORIOS      # lo usan template y JS
            if campo.es_obligatorio:
                campo.widget.attrs["data-required"] = "true"
            if self.bloqueado:
                campo.disabled = True

    def clean(self):
        cleaned = super().clean()
        if self.bloqueado:
            raise ValidationError("La propuesta está bloqueada y no admite modificaciones.")

        if self.accion == "enviar":
            faltantes = [
                self.fields[n].label or n
                for n in CAMPOS_OBLIGATORIOS
                if not str(cleaned.get(n) or "").strip()
            ]
            if faltantes:
                raise ValidationError("Completa los campos obligatorios: " + ", ".join(faltantes) + ".")
            if not self.instance.director_id:
                raise ValidationError("No tienes un Director asignado para recibir la propuesta.")
        return cleaned


class PlantillaWordForm(forms.Form):
    """Carga de la plantilla Word (.docx) para autocompletar el formulario."""

    MAX_MB = 5
    archivo = forms.FileField(
        label="Plantilla Word (.docx)",
        widget=forms.ClearableFileInput(attrs={"accept": ".docx"}),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith(".docx"):
            raise ValidationError("Solo se aceptan archivos Word con extensión .docx.")
        if archivo.size > self.MAX_MB * 1024 * 1024:
            raise ValidationError(f"El archivo no puede superar {self.MAX_MB} MB.")
        return archivo
