from django.test import SimpleTestCase
from apps.propuestas.services.montaje import _normalizar_fecha_str

class NormalizarFechaTests(SimpleTestCase):
    def test_valida_ddmmyyyy(self):
        self.assertEqual(_normalizar_fecha_str('12/03/2025'), '2025-03-12')

    def test_valida_iso(self):
        self.assertEqual(_normalizar_fecha_str('2025-03-12'), '2025-03-12')

    def test_invalida(self):
        self.assertIsNone(_normalizar_fecha_str('31/02/2025'))
        self.assertIsNone(_normalizar_fecha_str('foo'))
