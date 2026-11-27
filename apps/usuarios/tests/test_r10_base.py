from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.usuarios.models import Rol

User = get_user_model()


class PlantillaBaseR10Tests(TestCase):
    def setUp(self):
        self.password = "ClaveSegura123*"
        rol = Rol.objects.first() or Rol.objects.create(nombre="ESTUDIANTE")
        self.user = User.objects.create_user(
            correo_institucional="estudiante.r10@unipamplona.edu.co",
            password=self.password,
            nombre="Estudiante Prueba R10",
            cedula="1090123456",
            nombre_usuario="estudiante.r10",
            rol=rol,
        )
        self.dashboard_url = reverse("dashboard:inicio")
        self.logout_url = reverse("usuarios:logout")

    def test_elementos_comunes_en_pantalla_autenticada(self):
        self.client.force_login(self.user)
        response = self.client.get(self.dashboard_url, follow=True)
        html = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        # 1. Formulario POST con CSRF para cerrar sesión
        self.assertIn(f'action="{self.logout_url}"', html)
        self.assertIn('method="post"', html.lower())
        self.assertIn("csrfmiddlewaretoken", html)

        # 2. Menú lateral R9 y hoja de estilos institucional
        self.assertIn('id="sistraSidebar"', html)
        self.assertIn("css/sistra.css", html)

        # 4. Script de inactividad R4 en vistas autenticadas
        self.assertIn("js/inactividad.js", html)

    def test_cierre_sesion_funciona_por_post(self):
        self.client.force_login(self.user)
        response = self.client.post(self.logout_url)

        self.assertIn(response.status_code, (302, 200))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_mensajes_sistema_renderizan_con_role_alert(self):
        factory = RequestFactory()
        request = factory.get(self.dashboard_url)
        request.user = self.user

        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        MessageMiddleware(lambda req: None).process_request(request)

        messages.success(request, "MSG-01-01 Operación exitosa")
        html = render_to_string("base.html", request=request)

        self.assertIn('role="alert"', html)
        self.assertIn("MSG-01-01 Operación exitosa", html)
