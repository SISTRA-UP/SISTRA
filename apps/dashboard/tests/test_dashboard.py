from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Permiso, Rol, RolPermiso

Usuario = get_user_model()


class DashboardVistasTests(TestCase):
    def setUp(self):
        self.permiso = Permiso.objects.get(nombre='dashboard.ver')
        self.rol_admin = Rol.objects.get(nombre='Administrador')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.rol_director = Rol.objects.get(nombre='Director')

        self.admin = Usuario.objects.create_user(
            correo_institucional='admin.test@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_admin,
            nombre='Admin Test',
            cedula='900000001',
            nombre_usuario='admin_test',
            requiere_cambio_contrasena=False,
        )
        self.estudiante = Usuario.objects.create_user(
            correo_institucional='est.test@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_estudiante,
            nombre='Estudiante Test',
            cedula='900000002',
            nombre_usuario='est_test',
            requiere_cambio_contrasena=False,
        )

    def test_anonimo_redirige_a_login(self):
        respuesta = self.client.get(reverse('dashboard:inicio'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('usuarios:login'), respuesta.url)

    def test_usuario_sin_permiso_recibe_403(self):
        RolPermiso.objects.filter(rol=self.rol_estudiante, permiso=self.permiso).delete()
        self.client.force_login(self.estudiante)
        respuesta = self.client.get(reverse('dashboard:inicio'))
        self.assertEqual(respuesta.status_code, 403)

    def test_redirige_segun_rol_y_registra_auditoria(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('dashboard:inicio'), follow=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Administración')  # <- Cambiado aquí
        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.admin, accion='CONSULTA_DASHBOARD'
            ).exists()
        )

    def test_estudiante_no_puede_abrir_panel_administrador(self):
        self.client.force_login(self.estudiante)
        respuesta = self.client.get(reverse('dashboard:administrador'))
        self.assertEqual(respuesta.status_code, 403)