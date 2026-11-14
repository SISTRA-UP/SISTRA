"""SISTRA-07 · Pruebas del formulario de reactivación."""

from django.test import SimpleTestCase
from django.utils import timezone

from apps.informes.forms.aprobacion_reactivacion import (
    ReactivacionInformeForm,
)


class ReactivacionInformeFormTests(SimpleTestCase):

    def test_motivo_y_version_validos(self):
        fecha = timezone.now()

        formulario = ReactivacionInformeForm(
            data={
                "motivo": "  El informe fue rechazado por error.  ",
                "fecha_actualizacion": fecha.isoformat(),
            }
        )

        self.assertTrue(formulario.is_valid(), formulario.errors)

        self.assertEqual(
            formulario.cleaned_data["motivo"],
            "El informe fue rechazado por error.",
        )

        self.assertEqual(
            formulario.cleaned_data["fecha_actualizacion"],
            fecha,
        )

    def test_motivo_vacio_o_solo_espacios_no_es_valido(self):
        for motivo in ("", "   "):
            with self.subTest(motivo=motivo):
                formulario = ReactivacionInformeForm(
                    data={
                        "motivo": motivo,
                        "fecha_actualizacion": timezone.now().isoformat(),
                    }
                )

                self.assertFalse(formulario.is_valid())
                self.assertIn("motivo", formulario.errors)

    def test_sin_version_del_informe_no_es_valido(self):
        formulario = ReactivacionInformeForm(
            data={
                "motivo": "El rechazo se registró por equivocación.",
            }
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("fecha_actualizacion", formulario.errors)

    def test_version_con_formato_incorrecto_no_es_valida(self):
        formulario = ReactivacionInformeForm(
            data={
                "motivo": "El rechazo se registró por equivocación.",
                "fecha_actualizacion": "fecha-incorrecta",
            }
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("fecha_actualizacion", formulario.errors)