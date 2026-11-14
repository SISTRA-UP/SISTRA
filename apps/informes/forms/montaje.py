"""Formulario de montaje de informe (SISTRA-06).

Solo 3 campos: resultados, conclusiones, recomendaciones.
"""

from django import forms

from apps.informes.models import Informe


class InformeForm(forms.ModelForm):
    """Formulario para diligenciar el informe de Trabajo Social."""

    class Meta:
        model = Informe
        fields = ['resultados', 'conclusiones', 'recomendaciones']
        widgets = {
            'resultados': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 6,
                    'placeholder': 'Describa los resultados obtenidos en el Trabajo Social...',
                    'style': 'font-family: Inter, system-ui, sans-serif;',
                }
            ),
            'conclusiones': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 6,
                    'placeholder': 'Escriba las conclusiones del trabajo realizado...',
                    'style': 'font-family: Inter, system-ui, sans-serif;',
                }
            ),
            'recomendaciones': forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'rows': 6,
                    'placeholder': 'Incluya recomendaciones para futuros trabajos o continuidades...',
                    'style': 'font-family: Inter, system-ui, sans-serif;',
                }
            ),
        }

    def clean(self):
        """Valida que los 3 campos estén completos."""
        cleaned_data = super().clean()
        resultados = cleaned_data.get('resultados', '').strip()
        conclusiones = cleaned_data.get('conclusiones', '').strip()
        recomendaciones = cleaned_data.get('recomendaciones', '').strip()

        if not resultados or not conclusiones or not recomendaciones:
            raise forms.ValidationError(
                'Todos los campos (resultados, conclusiones y recomendaciones) '
                'son obligatorios para enviar el informe.'
            )

        return cleaned_data