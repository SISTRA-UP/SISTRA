"""SISTRA-07 · Aprobación de informe: pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test

from django.test import TestCase  # noqa: F401
"""


"""SISTRA-07 · Pruebas de validación de decisiones."""

from django.test import SimpleTestCase

from apps.informes.forms.aprobacion import DecisionInformeForm
from apps.propuestas.models import EstadoTramite


class DecisionInformeFormTests(SimpleTestCase):
    """Comprueba los campos obligatorios de cada decisión."""

    def test_aprobar_permite_observacion_vacia(self):
        formulario = DecisionInformeForm(
            data={
                "nuevo_estado": EstadoTramite.APROBADO,
                "observacion": "",
            }
        )

        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_modificacion_exige_observacion(self):
        formulario = DecisionInformeForm(
            data={
                "nuevo_estado": EstadoTramite.REQUIERE_MODIFICACION,
                "observacion": "   ",
            }
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("observacion", formulario.errors)

    def test_modificacion_con_observacion_es_valida(self):
        formulario = DecisionInformeForm(
            data={
                "nuevo_estado": EstadoTramite.REQUIERE_MODIFICACION,
                "observacion": "Explica mejor los resultados obtenidos.",
            }
        )

        self.assertTrue(formulario.is_valid(), formulario.errors)

    def test_rechazo_exige_tipo_y_observacion(self):
        formulario = DecisionInformeForm(
            data={
                "nuevo_estado": EstadoTramite.RECHAZADO,
                "observacion": "",
            }
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("tipo_rechazo", formulario.errors)
        self.assertIn("observacion", formulario.errors)

    def test_no_permite_decidir_subido_en_up(self):
        formulario = DecisionInformeForm(
            data={
                "nuevo_estado": EstadoTramite.SUBIDO_EN_UP,
            }
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("nuevo_estado", formulario.errors)