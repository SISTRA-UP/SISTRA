from datetime import date

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Carrera
from apps.personas.models import DirectorCarrera
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import ROL_DIRECTOR, ROL_ESTUDIANTE, Usuario
from apps.usuarios.servicios import crear_usuario


class UsuariosViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            'admin@unipamplona.edu.co', 'Clave-Segura-123',
            nombre='Admin', cedula='900000001', nombre_usuario='admin',
        )
        cls.derecho = Carrera.objects.get(codigo='52382')
        cls.director = crear_usuario(
            nombre='Diana', apellido='Rojas', cedula='900000002',
            correo='diana@unipamplona.edu.co', rol=ROL_DIRECTOR,
        )
        DirectorCarrera.objects.create(
            director=cls.director.director, carrera=cls.derecho,
            fecha_inicio=date.today(), activo=True,
        )
        cls.director_sin_carrera = crear_usuario(
            nombre='Sin', apellido='Carrera', cedula='900000003',
            correo='sin@unipamplona.edu.co', rol=ROL_DIRECTOR,
        )
        cls.url = reverse('parametrizacion:usuarios')

    def datos(self, **cambios):
        datos = {'cedula': '1001234567', 'nombre': 'Ana', 'apellido': 'Pérez',
                 'correo': 'ana.perez@unipamplona.edu.co', 'telefono': '3001234567'}
        datos.update(cambios)
        return datos

    def crear_estudiante(self):
        with self.captureOnCommitCallbacks(execute=True):
            return crear_usuario(
                nombre='Luis', apellido='Díaz', cedula='1007654321',
                correo='luis@unipamplona.edu.co', rol=ROL_ESTUDIANTE,
            )

    # --- Acceso ---
    def test_sin_sesion_redirige_al_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_el_administrador_no_crea_usuarios(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_un_estudiante_no_crea_usuarios(self):
        self.client.force_login(self.crear_estudiante())
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_un_estudiante_no_entra_al_modulo(self):
        self.client.force_login(self.crear_estudiante())
        self.assertEqual(self.client.get(reverse('parametrizacion:parametrizacion')).status_code, 403)

    def test_el_director_entra_al_modulo_y_va_a_usuarios(self):
        self.client.force_login(self.director)
        respuesta = self.client.get(reverse('parametrizacion:parametrizacion'))
        self.assertRedirects(respuesta, self.url)

    def test_el_administrador_ve_las_secciones_pero_no_usuarios(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('parametrizacion:parametrizacion'))
        self.assertContains(respuesta, 'Periodo académico')
        self.assertNotContains(respuesta, 'aria-current="page">Usuarios')

    def test_el_director_solo_ve_usuarios_en_el_menu(self):
        self.client.force_login(self.director)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'aria-current="page">Usuarios')
        self.assertNotContains(respuesta, 'Periodo académico')
        self.assertNotContains(respuesta, 'Estados del proceso')

    # --- Crear estudiantes ---
    def test_el_director_ve_el_formulario(self):
        self.client.force_login(self.director)
        self.assertContains(self.client.get(self.url), 'Crear estudiante uno a uno')

    def test_director_crea_estudiante_en_su_carrera_y_audita(self):
        self.client.force_login(self.director)
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(self.url, self.datos())
        self.assertRedirects(respuesta, self.url)
        estudiante = Usuario.objects.get(correo_institucional='ana.perez@unipamplona.edu.co')
        self.assertEqual(estudiante.estudiante.inscripciones.get().carrera, self.derecho)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Auditoria.objects.filter(
            accion='Crear usuario', resultado='Éxito', usuario=self.director).exists())

    def test_error_se_muestra_y_se_audita(self):
        self.client.force_login(self.director)
        respuesta = self.client.post(self.url, self.datos(correo='ana@gmail.com'))
        self.assertContains(respuesta, 'El correo debe ser institucional.')
        self.assertTrue(Auditoria.objects.filter(resultado='Fallo').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_la_respuesta_no_incluye_la_contrasena(self):
        self.client.force_login(self.director)
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(self.url, self.datos(), follow=True)
        self.assertNotContains(respuesta, 'Contraseña temporal:')

    def test_director_sin_carrera_recibe_aviso(self):
        self.client.force_login(self.director_sin_carrera)
        self.assertContains(self.client.get(self.url), 'No tiene una carrera asignada')

    # --- Cerrar sesión ---
    def test_cerrar_sesion_por_post(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(reverse('parametrizacion:salir')).status_code, 302)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_cerrar_sesion_no_acepta_get(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(reverse('parametrizacion:salir')).status_code, 405)


class DirectoresViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            'admin@unipamplona.edu.co', 'Clave-Segura-123',
            nombre='Admin', cedula='900000001', nombre_usuario='admin',
        )
        cls.derecho = Carrera.objects.get(codigo='52382')
        cls.url = reverse('parametrizacion:directores')

    def datos(self, **cambios):
        datos = {'nombre': 'Diana', 'apellido': 'Rojas', 'cedula': '1005005005',
                 'correo': 'diana.rojas@unipamplona.edu.co', 'telefono': '',
                 'carrera': self.derecho.pk}
        datos.update(cambios)
        return datos

    def test_un_director_no_entra(self):
        with self.captureOnCommitCallbacks(execute=True):
            director = crear_usuario(
                nombre='Otro', apellido='Director', cedula='900000009',
                correo='otro@unipamplona.edu.co', rol=ROL_DIRECTOR,
            )
        self.client.force_login(director)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_crea_director_y_lo_asigna(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(self.url, self.datos())
        self.assertRedirects(respuesta, self.url)
        usuario = Usuario.objects.get(correo_institucional='diana.rojas@unipamplona.edu.co')
        asignacion = usuario.director.asignaciones.get()
        self.assertEqual((asignacion.carrera, asignacion.activo), (self.derecho, True))
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Auditoria.objects.filter(accion='Asignar director a carrera').exists())

    def test_segundo_director_en_la_misma_carrera_se_rechaza_sin_crear_nada(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, self.datos())
        respuesta = self.client.post(self.url, self.datos(
            cedula='1006006006', correo='otra@unipamplona.edu.co'))
        self.assertContains(respuesta, 'ya tiene un director activo')
        self.assertFalse(Usuario.objects.filter(correo_institucional='otra@unipamplona.edu.co').exists())

    def test_el_director_creado_puede_crear_estudiantes_pero_no_directores(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, self.datos())
        director = Usuario.objects.get(correo_institucional='diana.rojas@unipamplona.edu.co')
        self.client.force_login(director)
        self.assertEqual(self.client.get(reverse('parametrizacion:usuarios')).status_code, 200)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_correo_no_institucional_se_rechaza(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, self.datos(correo='diana@gmail.com'))
        self.assertContains(respuesta, 'El correo debe ser institucional.')