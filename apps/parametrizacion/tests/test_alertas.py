from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion import servicios
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Rol, Usuario


class AlertasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            'admin@unipamplona.edu.co', 'Clave-Segura-123',
            nombre='Admin', cedula='900000001', nombre_usuario='admin',
        )
        rol_dir, _ = Rol.objects.get_or_create(nombre='Director')
        cls.director = Usuario.objects.create_user(
            correo_institucional='diana@unipamplona.edu.co',
            password='Director-Test-1',
            nombre='Diana Rojas',
            cedula='900000002',
            nombre_usuario='diana.rojas',
            rol=rol_dir,
            requiere_cambio_contrasena=False,
        )
        cls.url = reverse('parametrizacion:alertas')

    def setUp(self):
        self.client.force_login(self.admin)

    def datos(self, **cambios):
        datos = {
            'verde_hasta_dias': '7', 'amarillo_hasta_dias': '14',
            'frecuencia_recordatorio_dias': '7', 'dias_archivado_propuesta': '',
            'dias_archivado_informe': '', 'url_up': '',
        }
        datos.update(cambios)
        return datos

    def test_el_director_no_entra(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_muestra_los_valores_iniciales(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'value="7"')
        self.assertContains(respuesta, 'value="14"')
        self.assertContains(respuesta, '15 días o más')

    def test_guarda_valores_nuevos_y_audita(self):
        respuesta = self.client.post(self.url, self.datos(
            verde_hasta_dias='10', amarillo_hasta_dias='20', frecuencia_recordatorio_dias='5',
            dias_archivado_propuesta='30', url_up='https://up.unipamplona.edu.co',
        ))
        self.assertRedirects(respuesta, self.url)
        self.assertEqual(servicios.obtener_entero('semaforo.verde_hasta_dias'), 10)
        self.assertEqual(servicios.obtener_entero('semaforo.amarillo_hasta_dias'), 20)
        self.assertEqual(servicios.obtener_entero('recordatorio.frecuencia_dias'), 5)
        self.assertEqual(servicios.obtener_entero('dias_archivado_propuesta_rechazada'), 30)
        self.assertEqual(servicios.obtener('url_up'), 'https://up.unipamplona.edu.co')
        self.assertEqual(Auditoria.objects.filter(accion='Modificar parámetro').count(), 5)

    def test_sin_cambios_no_escribe_ni_audita(self):
        respuesta = self.client.post(self.url, self.datos(), follow=True)
        self.assertContains(respuesta, 'No hubo cambios')
        self.assertFalse(Auditoria.objects.filter(accion='Modificar parámetro').exists())

    def test_amarillo_debe_ser_mayor_que_verde(self):
        respuesta = self.client.post(self.url, self.datos(amarillo_hasta_dias='7'))
        self.assertContains(respuesta, 'El límite del amarillo debe ser mayor que el del verde.')

    def test_rechaza_cero_y_texto(self):
        respuesta = self.client.post(self.url, self.datos(verde_hasta_dias='0'))
        self.assertContains(respuesta, 'Ingrese un número entero mayor que cero.')
        respuesta = self.client.post(self.url, self.datos(frecuencia_recordatorio_dias='abc'))
        self.assertContains(respuesta, 'Ingrese un número entero mayor que cero.')

    def test_la_direccion_de_up_debe_ser_https(self):
        respuesta = self.client.post(self.url, self.datos(url_up='http://up.edu.co'))
        self.assertContains(respuesta, 'La dirección debe empezar por https://')

    def test_un_error_no_guarda_nada(self):
        self.client.post(self.url, self.datos(verde_hasta_dias='9', amarillo_hasta_dias='3'))
        self.assertEqual(servicios.obtener_entero('semaforo.verde_hasta_dias'), 7)

    def test_color_semaforo_con_los_valores_iniciales(self):
        casos = {0: 'verde', 7: 'verde', 8: 'amarillo', 14: 'amarillo', 15: 'rojo', -3: 'verde'}
        for dias, esperado in casos.items():
            self.assertEqual(servicios.color_semaforo(dias), esperado, dias)

    def test_color_semaforo_con_valores_guardados(self):
        servicios.guardar('semaforo.verde_hasta_dias', 3, self.admin)
        servicios.guardar('semaforo.amarillo_hasta_dias', 5, self.admin)
        self.assertEqual(
            [servicios.color_semaforo(d) for d in (3, 4, 5, 6)],
            ['verde', 'amarillo', 'amarillo', 'rojo'],
        )