import re
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.session import SessionStorage
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest, HttpResponse
from django.test import TestCase
from django.urls import reverse



from apps.usuarios.models import Rol

User = get_user_model()


class PlantillaBaseR10Tests(TestCase):
    def setUp(self):
        self.password = "ClaveSegura123*"
        self.dashboard_url = reverse("dashboard:inicio")
        self.logout_url = reverse("usuarios:logout")

        # Asegura existencia de roles base si la tabla estuviera vacía
        if not Rol.objects.exists():
            for nombre in ("Administrador", "Director", "Estudiante"):
                Rol.objects.create(nombre=nombre)

        self.roles = list(Rol.objects.all())

    def _crear_usuario_para_rol(self, rol, indice):
        return User.objects.create_user(
            correo_institucional=f"r10.rol{indice}@unipamplona.edu.co",
            password=self.password,
            nombre=f"Usuario Prueba {rol.nombre}",
            cedula=f"1090999{indice:03d}",
            nombre_usuario=f"r10_rol_{indice}",
            rol=rol,
        )

    def _extraer_rutas_menu(self, html):
        bloque_nav = re.search(
            r'<nav[^>]*aria-label="Opciones disponibles para tu rol"[^>]*>(.*?)</nav>',
            html,
            re.DOTALL,
        )
        if not bloque_nav:
            return []
        rutas = re.findall(r'href="(/[^"]*)"', bloque_nav.group(1))
        # Filtra rutas internas reales (excluye '#' o cierre de sesión)
        return sorted({r for r in rutas if r != self.logout_url})

    def _inyectar_mensaje_en_sesion(self, texto):
        req = HttpRequest()
        session = self.client.session
        req.session = session
        resp = HttpResponse()
        storage = FallbackStorage(req)
        storage.add(messages.ERROR, texto)
        storage.update(resp)
        session.save()
        for nombre, morsel in resp.cookies.items():
            self.client.cookies[nombre] = morsel.value

    def test_pantallas_de_cada_rol_tienen_un_solo_logout_y_un_solo_menu(self):
        for idx, rol in enumerate(self.roles, start=1):
            usuario = self._crear_usuario_para_rol(rol, idx)
            self.client.force_login(usuario)

            resp_inicio = self.client.get(self.dashboard_url, follow=True)
            self.assertEqual(resp_inicio.status_code, 200)
            html_inicio = resp_inicio.content.decode("utf-8")

            rutas_a_probar = [self.dashboard_url] + self._extraer_rutas_menu(html_inicio)

            for ruta in dict.fromkeys(rutas_a_probar):
                with self.subTest(rol=rol.nombre, ruta=ruta):
                    resp = self.client.get(ruta, follow=True)
                    if resp.status_code != 200:
                        continue
                    html = resp.content.decode("utf-8")

                    self.assertEqual(
                        html.count(f'action="{self.logout_url}"'),
                        1,
                        f"Se esperaba 1 formulario de cierre de sesión en {ruta} ({rol.nombre})",
                    )
                    self.assertEqual(
                        html.count('aria-label="Opciones disponibles para tu rol"'),
                        1,
                        f"Se esperaba 1 menú lateral de R9 en {ruta} ({rol.nombre})",
                    )

    def test_mensajes_sistema_aparecen_una_sola_vez_en_pantallas_internas(self):
        mensaje_prueba = "No puedes inactivar tu propia cuenta."
        for idx, rol in enumerate(self.roles, start=10):
            usuario = self._crear_usuario_para_rol(rol, idx)
            self.client.force_login(usuario)

            resp_inicio = self.client.get(self.dashboard_url, follow=True)
            html_inicio = resp_inicio.content.decode("utf-8")
            rutas_a_probar = [self.dashboard_url] + self._extraer_rutas_menu(html_inicio)

            for ruta in dict.fromkeys(rutas_a_probar):
                with self.subTest(rol=rol.nombre, ruta=ruta):
                    self._inyectar_mensaje_en_sesion(mensaje_prueba)
                    resp = self.client.get(ruta, follow=True)
                    if resp.status_code != 200:
                        continue
                    html = resp.content.decode("utf-8")

                    self.assertEqual(
                        html.count(mensaje_prueba),
                        1,
                        f"El mensaje se duplicó o no apareció en {ruta} ({rol.nombre})",
                    )
