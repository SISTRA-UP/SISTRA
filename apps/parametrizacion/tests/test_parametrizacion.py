"""SISTRA-11 · Parametrización: pruebas de acceso y vistas principales.

Solo el Administrador (permiso `sistema.parametrizar`) puede entrar.
Directores y Estudiantes deben recibir 403 en todas las URLs del módulo.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Actividad, Carrera, Plantilla
from apps.usuarios.models import Permiso, Rol, RolPermiso, Usuario


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
    rol, _ = Rol.objects.get_or_create(nombre='Director')
    return Usuario.objects.create_user(
        correo_institucional=correo,
        password='Director-Test-1',
        nombre='Director Test',
        cedula=cedula,
        nombre_usuario=correo.split('@')[0].replace('.', '_'),
        rol=rol,
        requiere_cambio_contrasena=False,
    )


def _crear_estudiante():
    rol, _ = Rol.objects.get_or_create(nombre='Estudiante')
    return Usuario.objects.create_user(
        correo_institucional='est@unipamplona.edu.co',
        password='Estudiante-Test-1',
        nombre='Estudiante Test',
        cedula='100999001',
        nombre_usuario='est',
        rol=rol,
        requiere_cambio_contrasena=False,
    )


# URLs del módulo que solo el Administrador puede ver (permiso sistema.parametrizar)
URLS_SOLO_ADMIN = [
    'parametrizacion:parametrizacion',
    'parametrizacion:periodos',
    'parametrizacion:alertas',
    'parametrizacion:estados',
    'parametrizacion:documentos',
]


class AccesoModuloTests(TestCase):
    """Verifica que solo el Administrador accede; Director y Estudiante reciben 403."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_admin()
        cls.director = _crear_director('900000002', 'dir@unipamplona.edu.co')
        cls.estudiante = _crear_estudiante()
        cls.actividad = Actividad.objects.create(
            nombre='Etapa de acceso', descripcion='', orden=999,
            obligatoria=False, estado='Activo',
        )
        cls.plantilla = Plantilla.objects.create(
            nombre='Plantilla de acceso', tipo='otro', estado='Activo',
        )

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

    def test_director_recibe_403_en_operaciones_de_escritura_y_descarga(self):
        self.client.force_login(self.director)
        operaciones = [
            ('POST', reverse('parametrizacion:actividad_nueva'), {
                'nombre': 'Etapa no autorizada', 'descripcion': '', 'orden': 1000,
                'obligatoria': False, 'estado': 'Activo',
            }),
            ('POST', reverse('parametrizacion:actividad_editar', args=[self.actividad.pk]), {
                'nombre': 'Etapa modificada', 'descripcion': '', 'orden': 999,
                'obligatoria': False, 'estado': 'Activo',
            }),
            ('POST', reverse('parametrizacion:actividad_eliminar', args=[self.actividad.pk]), {}),
            ('POST', reverse('parametrizacion:documentos_version', args=[self.plantilla.pk]), {}),
            ('GET', reverse('parametrizacion:documentos_descargar', args=[self.plantilla.pk]), {}),
        ]

        for metodo, url, datos in operaciones:
            with self.subTest(metodo=metodo, url=url):
                if metodo == 'POST':
                    resp = self.client.post(url, datos)
                else:
                    resp = self.client.get(url)
                self.assertEqual(resp.status_code, 403)

    def test_administrador_accede_al_inicio(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('parametrizacion:parametrizacion'))
        self.assertEqual(resp.status_code, 200)

    def test_administrador_ve_secciones_principales(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('parametrizacion:parametrizacion'))
        self.assertContains(resp, 'Periodo')

