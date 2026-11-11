"""SISTRA-11 · Parametrización: pruebas de acceso y vistas principales.

Solo el Administrador (permiso `sistema.parametrizar`) puede entrar.
Directores y Estudiantes deben recibir 403 en todas las URLs del módulo.
"""
from datetime import date

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Carrera
from apps.personas.models import DirectorCarrera
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import ROL_DIRECTOR, ROL_ESTUDIANTE, Permiso, Rol, RolPermiso, Usuario
from apps.usuarios.servicios import crear_usuario


def _crear_admin():
    """Crea un Administrador con el permiso sistema.parametrizar."""
    rol, _ = Rol.objects.get_or_create(nombre='Administrador')
    usuario = Usuario.objects.create_user(
        correo_institucional='admin@unipamplona.edu.co',
        password='Admin-Segura-1',
        nombre='Admin Test',
        cedula='900000001',
        nombre_usuario='admin.test',
        rol=rol,
        requiere_cambio_contrasena=False,
    )
    permiso, _ = Permiso.objects.get_or_create(
        nombre='sistema.parametrizar',
        defaults={'descripcion': 'Acceso a parametrización', 'estado': 'Activo'},
    )
    RolPermiso.objects.get_or_create(rol=rol, permiso=permiso)
    return usuario


def _crear_director(cedula, correo):
    """Crea un Director sin carrera asignada."""
    return crear_usuario(
        nombre='Director', apellido='Test',
        cedula=cedula, correo=correo,
        rol=ROL_DIRECTOR,
    )


def _crear_estudiante():
    return crear_usuario(
        nombre='Estudiante', apellido='Test',
        cedula='100999001', correo='est@unipamplona.edu.co',
        rol=ROL_ESTUDIANTE,
    )


# URLs del módulo que solo el Administrador puede ver (permiso sistema.parametrizar)
URLS_SOLO_ADMIN = [
    'parametrizacion:parametrizacion',
    'parametrizacion:periodos',
    'parametrizacion:alertas',
    'parametrizacion:estados',
    'parametrizacion:directores',
    'parametrizacion:documentos',
]


class AccesoModuloTests(TestCase):
    """Verifica que solo el Administrador accede; Director y Estudiante reciben 403."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_admin()
        cls.director = _crear_director('900000002', 'dir@unipamplona.edu.co')
        cls.estudiante = _crear_estudiante()

    def test_sin_sesion_redirige(self):
        for nombre in URLS_SOLO_ADMIN:
            with self.subTest(url=nombre):
                resp = self.client.get(reverse(nombre))
                self.assertEqual(resp.status_code, 302, msg=f'{nombre} debe redirigir sin sesión')

    def test_director_recibe_403_en_todas_las_urls(self):
        self.client.force_login(self.director)
        for nombre in URLS_SOLO_ADMIN:
            with self.subTest(url=nombre):
                resp = self.client.get(reverse(nombre))
                self.assertEqual(resp.status_code, 403, msg=f'Director debe recibir 403 en {nombre}')

    def test_estudiante_recibe_403_en_todas_las_urls(self):
        self.client.force_login(self.estudiante)
        for nombre in URLS_SOLO_ADMIN:
            with self.subTest(url=nombre):
                resp = self.client.get(reverse(nombre))
                self.assertEqual(resp.status_code, 403, msg=f'Estudiante debe recibir 403 en {nombre}')

    def test_administrador_accede_al_inicio(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('parametrizacion:parametrizacion'))
        self.assertEqual(resp.status_code, 200)

    def test_administrador_ve_secciones_principales(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('parametrizacion:parametrizacion'))
        self.assertContains(resp, 'Periodo')


class DirectoresViewTests(TestCase):
    """Creación de directores: solo el Administrador puede hacerlo."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_admin()
        cls.derecho = Carrera.objects.get(codigo='52382')
        cls.url = reverse('parametrizacion:directores')

    def datos(self, **cambios):
        base = {
            'nombre': 'Diana', 'apellido': 'Rojas',
            'cedula': '1005005005', 'correo': 'diana.rojas@unipamplona.edu.co',
            'carrera': self.derecho.pk,
        }
        base.update(cambios)
        return base

    def test_director_no_puede_crear_directores(self):
        director = _crear_director('900000010', 'dir10@unipamplona.edu.co')
        self.client.force_login(director)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_crea_director_y_lo_asigna(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(self.url, self.datos())
        self.assertRedirects(resp, self.url)
        usuario = Usuario.objects.get(correo_institucional='diana.rojas@unipamplona.edu.co')
        asignacion = usuario.director.asignaciones.get()
        self.assertEqual(asignacion.carrera, self.derecho)
        self.assertTrue(asignacion.activo)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Auditoria.objects.filter(accion='Asignar director a carrera').exists())

    def test_segundo_director_en_misma_carrera_se_rechaza(self):
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, self.datos())
        resp = self.client.post(self.url, self.datos(
            cedula='1006006006', correo='otra@unipamplona.edu.co'))
        self.assertContains(resp, 'ya tiene un director activo')
        self.assertFalse(Usuario.objects.filter(
            correo_institucional='otra@unipamplona.edu.co').exists())

    def test_correo_no_institucional_se_rechaza(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.url, self.datos(correo='diana@gmail.com'))
        self.assertContains(resp, 'El correo debe ser institucional.')
