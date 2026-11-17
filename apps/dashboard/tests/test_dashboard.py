from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Permiso, Rol, RolPermiso

Usuario = get_user_model()


class DashboardVistasTests(TestCase):
    def setUp(self):
        self.permiso = Permiso.objects.get(nombre='dashboard.ver')
        self.rol_admin = Rol.objects.get(nombre='Administrador')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.rol_director = Rol.objects.get(nombre='Director')

        self.facultad = Facultad.objects.create(nombre='Facultad de Ingenierías')
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería de Sistemas',
            codigo='IS-TEST',
        )

        self.admin = Usuario.objects.create_user(
            correo_institucional='admin.test@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_admin,
            nombre='Admin Test',
            cedula='900000001',
            nombre_usuario='admin_test',
            requiere_cambio_contrasena=False,
        )
        self.director_user = Usuario.objects.create_user(
            correo_institucional='dir.test@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_director,
            nombre='Director Test',
            cedula='900000003',
            nombre_usuario='dir_test',
            requiere_cambio_contrasena=False,
        )
        self.director = Director.objects.create(usuario=self.director_user)
        DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )

        self.estudiante_user = Usuario.objects.create_user(
            correo_institucional='est.test@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_estudiante,
            nombre='Estudiante Test',
            cedula='900000002',
            nombre_usuario='est_test',
            requiere_cambio_contrasena=False,
        )
        self.estudiante = Estudiante.objects.create(usuario=self.estudiante_user)
        EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            estado=EstadoInscripcion.ACTIVO,
        )

    def test_anonimo_redirige_a_login(self):
        respuesta = self.client.get(reverse('dashboard:inicio'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('usuarios:login'), respuesta.url)

    def test_usuario_sin_permiso_recibe_403(self):
        RolPermiso.objects.filter(rol=self.rol_estudiante, permiso=self.permiso).delete()
        self.client.force_login(self.estudiante_user)
        respuesta = self.client.get(reverse('dashboard:inicio'))
        self.assertEqual(respuesta.status_code, 403)

    def test_panel_administrador_muestra_tarjetas_filtros_y_accesos(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard:inicio'), follow=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Estudiantes activos')
        self.assertContains(respuesta, 'Propuestas en revisión')
        self.assertContains(respuesta, 'Roles y permisos')
        self.assertContains(respuesta, 'Parametrización')
        self.assertContains(respuesta, 'Filtros de consulta')
        self.assertContains(respuesta, 'Panorama por carrera')
        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.admin, accion='CONSULTA_DASHBOARD'
            ).exists()
        )

    def test_panel_director_muestra_tarjetas_tabla_estudiantes_y_accesos(self):
        self.client.force_login(self.director_user)
        respuesta = self.client.get(reverse('dashboard:inicio'), follow=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Mis estudiantes')
        self.assertContains(respuesta, 'Propuestas en revisión')
        self.assertContains(respuesta, 'Subido en UP por verificar')
        self.assertContains(respuesta, 'Aprobación de propuestas')
        self.assertContains(respuesta, 'Registrar estudiantes')
        self.assertContains(respuesta, 'Filtros de consulta')
        self.assertContains(respuesta, 'Estudiante Test')

    def test_panel_estudiante_muestra_avance_y_accesos_rapidos(self):
        self.client.force_login(self.estudiante_user)
        respuesta = self.client.get(reverse('dashboard:inicio'), follow=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Mi Trabajo Social')
        self.assertContains(respuesta, 'Montar propuesta')
        self.assertContains(respuesta, 'Montar informe')
        self.assertContains(respuesta, 'Cargue UP propuesta')
        self.assertContains(respuesta, 'Avance general del proceso')
        self.assertContains(respuesta, 'Ingeniería de Sistemas')

    def test_estudiante_no_puede_abrir_panel_administrador(self):
        self.client.force_login(self.estudiante_user)
        respuesta = self.client.get(reverse('dashboard:administrador'))
        self.assertEqual(respuesta.status_code, 403)
        
