from django.test import TestCase

from apps.parametrizacion import servicios
from apps.parametrizacion.models import Parametro
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Usuario


class ParametrosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            'admin@unipamplona.edu.co', 'Clave-Segura-123',
            nombre='Admin', cedula='900000001', nombre_usuario='admin',
        )

    def test_devuelve_el_valor_inicial_si_no_hay_uno_guardado(self):
        self.assertEqual(servicios.obtener('semaforo.verde_hasta_dias'), '7')
        self.assertEqual(servicios.obtener_entero('semaforo.amarillo_hasta_dias'), 14)

    def test_sin_valor_inicial_devuelve_none(self):
        self.assertIsNone(servicios.obtener('url_up'))
        self.assertIsNone(servicios.obtener_entero('url_up'))

    def test_clave_desconocida(self):
        with self.assertRaises(KeyError):
            servicios.obtener('no.existe')
        with self.assertRaises(KeyError):
            servicios.guardar('no.existe', '1', self.admin)

    def test_guardar_crea_y_audita(self):
        self.assertTrue(servicios.guardar('semaforo.verde_hasta_dias', 10, self.admin))
        self.assertEqual(servicios.obtener_entero('semaforo.verde_hasta_dias'), 10)
        registro = Auditoria.objects.get(accion='Modificar parámetro')
        self.assertIn('semaforo.verde_hasta_dias', registro.detalle)
        self.assertIn("'7'", registro.detalle)

    def test_guardar_actualiza_el_existente(self):
        servicios.guardar('semaforo.verde_hasta_dias', 10, self.admin)
        servicios.guardar('semaforo.verde_hasta_dias', 12, self.admin)
        self.assertEqual(Parametro.objects.filter(clave='semaforo.verde_hasta_dias').count(), 1)
        self.assertEqual(servicios.obtener_entero('semaforo.verde_hasta_dias'), 12)

    def test_guardar_el_mismo_valor_no_cambia_ni_audita(self):
        servicios.guardar('semaforo.verde_hasta_dias', 10, self.admin)
        self.assertFalse(servicios.guardar('semaforo.verde_hasta_dias', 10, self.admin))
        self.assertEqual(Auditoria.objects.filter(accion='Modificar parámetro').count(), 1)

    def test_guardar_el_valor_inicial_no_escribe_nada(self):
        self.assertFalse(servicios.guardar('semaforo.verde_hasta_dias', 7, self.admin))
        self.assertFalse(Parametro.objects.exists())
        