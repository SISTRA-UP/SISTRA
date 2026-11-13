"""SISTRA-07 · Pruebas de acceso a la bandeja de informes."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import Director, DirectorCarrera
from apps.usuarios.models import Permiso, Rol, RolPermiso


class AccesoAprobacionInformeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        Usuario = get_user_model()

        cls.rol_director = Rol.objects.get(nombre="Director")
        rol_administrador = Rol.objects.get(nombre="Administrador")
        rol_estudiante = Rol.objects.get(nombre="Estudiante")

        cls.director = Usuario.objects.create_user(
            correo_institucional="director@example.com",
            nombre="Director de prueba",
            cedula="100000001",
            nombre_usuario="director_prueba",
            password="ClavePruebas2026!",
            rol=cls.rol_director,
            requiere_cambio_contrasena=False,
        )

        cls.administrador = Usuario.objects.create_user(
            correo_institucional="administrador@example.com",
            nombre="Administrador de prueba",
            cedula="100000002",
            nombre_usuario="administrador_prueba",
            password="ClavePruebas2026!",
            rol=rol_administrador,
            requiere_cambio_contrasena=False,
        )

        cls.estudiante = Usuario.objects.create_user(
            correo_institucional="estudiante@example.com",
            nombre="Estudiante de prueba",
            cedula="100000003",
            nombre_usuario="estudiante_prueba",
            password="ClavePruebas2026!",
            rol=rol_estudiante,
            requiere_cambio_contrasena=False,
        )

        facultad = Facultad.objects.create(
            nombre="Facultad de prueba",
        )

        carrera = Carrera.objects.create(
            facultad=facultad,
            nombre="Carrera de prueba",
            codigo="PRUEBA-07",
        )

        perfil_director = Director.objects.create(
            usuario=cls.director,
        )

        cls.asignacion = DirectorCarrera.objects.create(
            director=perfil_director,
            carrera=carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )

    def setUp(self):
        self.url = reverse("informes:aprobacion")

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("next=", respuesta.url)

    def test_administrador_no_puede_entrar(self):
        self.client.force_login(self.administrador)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 403)

    def test_estudiante_no_puede_entrar(self):
        self.client.force_login(self.estudiante)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 403)

    def test_director_con_permiso_y_asignacion_puede_entrar(self):
        self.client.force_login(self.director)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 200)
        self.assertTemplateUsed(
            respuesta,
            "informes/aprobacion/bandeja.html",
        )
        self.assertContains(
            respuesta,
            "No hay informes disponibles para revisar.",
        )

    def test_director_sin_asignacion_activa_no_puede_entrar(self):
        self.asignacion.activo = False
        self.asignacion.save(update_fields=["activo"])

        self.client.force_login(self.director)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 403)

    def test_director_sin_permiso_no_puede_entrar(self):
        permiso = Permiso.objects.get(nombre="informe.aprobar")

        RolPermiso.objects.filter(
            rol=self.rol_director,
            permiso=permiso,
        ).delete()

        self.client.force_login(self.director)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 403)