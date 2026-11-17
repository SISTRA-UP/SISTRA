
"""SISTRA-12 · Pruebas del formulario de reportes."""

from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from apps.reportes.forms.reportes import (
    FormularioReporte,
    MSG_REP_01,
    MSG_REP_03,
)


class FormularioReporteTests(SimpleTestCase):
    """Pruebas de validación del formulario de reportes."""

    def test_fechas_obligatorias(self):
        """El formulario debe exigir las dos fechas."""
        formulario = FormularioReporte(data={})

        self.assertFalse(formulario.is_valid())

        self.assertEqual(
            formulario.errors['filterDateStart'][0],
            MSG_REP_01,
        )

        self.assertEqual(
            formulario.errors['filterDateEnd'][0],
            MSG_REP_01,
        )

    def test_rango_de_fechas_valido(self):
        """El formulario acepta un rango de fechas correcto."""
        hoy = timezone.localdate()
        fecha_desde = hoy - timedelta(days=10)

        formulario = FormularioReporte(data={
            'filterDateStart': fecha_desde.isoformat(),
            'filterDateEnd': hoy.isoformat(),
        })

        self.assertTrue(
            formulario.is_valid(),
            formulario.errors,
        )

    def test_fecha_desde_futura(self):
        """La fecha inicial no puede ser posterior a hoy."""
        hoy = timezone.localdate()
        fecha_futura = hoy + timedelta(days=1)

        formulario = FormularioReporte(data={
            'filterDateStart': fecha_futura.isoformat(),
            'filterDateEnd': fecha_futura.isoformat(),
        })

        self.assertFalse(formulario.is_valid())

        self.assertIn(
            MSG_REP_03,
            formulario.errors['filterDateStart'],
        )

    def test_fecha_hasta_anterior_a_desde(self):
        """La fecha final no puede ser anterior a la inicial."""
        hoy = timezone.localdate()
        fecha_desde = hoy - timedelta(days=5)
        fecha_hasta = hoy - timedelta(days=10)

        formulario = FormularioReporte(data={
            'filterDateStart': fecha_desde.isoformat(),
            'filterDateEnd': fecha_hasta.isoformat(),
        })

        self.assertFalse(formulario.is_valid())

        self.assertIn(
            MSG_REP_03,
            formulario.errors['filterDateEnd'],
        )
