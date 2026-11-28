import re
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpRequest, HttpResponse
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import Director, DirectorCarrera, Estudiante, EstudianteCarrera
from apps.usuarios.models import Rol

User = get_user_model()


class PlantillaBaseR10Tests(TestCase):
    def setUp(self):
        self.password = "ClaveSegura123*"
        self.dashboard_url = reverse("dashboard:inicio")
        self.logout_url = reverse("usuarios:logout")

        if not Rol.objects.exists():
            for nombre in ("Administrador", "Director", "Estudiante"):
                Rol.objects.create(nombre=nombre)

        self.roles = list(Rol.objects.all())

    def _crear_usuario_para_rol(self, rol, indice):
        usuario = User.objects.create_user(
            correo_institucional=f"r10.rol{indice}@unipamplona.edu.co",
            password=self.password,
            nombre=f"Usuario Prueba {rol.nombre}",
            cedula=f"1090999{indice:03d}",
            nombre_usuario=f"r10_rol_{indice}",
            rol=rol,
            # Sin esto, cada pantalla redirige a «Cambiar contraseña».
            requiere_cambio_contrasena=False,
        )
        # Con su perfil y su carrera, cada rol entra a sus pantallas y no recibe 403.
        facultad, _ = Facultad.objects.get_or_create(nombre="Facultad R10")
        carrera, _ = Carrera.objects.get_or_create(
            codigo=f"R10-{indice}",
            defaults={"facultad": facultad, "nombre": f"Carrera R10 {indice}"},
        )
        if rol.nombre == "Estudiante":
            estudiante = Estudiante.objects.create(usuario=usuario)
            EstudianteCarrera.objects.create(estudiante=estudiante, carrera=carrera, estado="Activo")
        elif rol.nombre == "Director":
            director = Director.objects.create(usuario=usuario)
            DirectorCarrera.objects.create(
                director=director, carrera=carrera, fecha_inicio=timezone.localdate(), activo=True
            )
        return usuario

    def _extraer_rutas_menu(self, html):
        bloque_nav = re.search(
            r'<nav[^>]*aria-label="Opciones disponibles para tu rol"[^>]*>(.*?)</nav>',
            html,
            re.DOTALL,
        )
        if not bloque_nav:
            return []
        rutas = re.findall(r'href="(/[^"]*)"', bloque_nav.group(1))
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
                    self.assertEqual(resp.status_code, 200)
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
            self.assertEqual(resp_inicio.status_code, 200)
            html_inicio = resp_inicio.content.decode("utf-8")
            rutas_a_probar = [self.dashboard_url] + self._extraer_rutas_menu(html_inicio)

            for ruta in dict.fromkeys(rutas_a_probar):
                with self.subTest(rol=rol.nombre, ruta=ruta):
                    self._inyectar_mensaje_en_sesion(mensaje_prueba)
                    resp = self.client.get(ruta, follow=True)
                    self.assertEqual(resp.status_code, 200)
                    html = resp.content.decode("utf-8")

                    self.assertEqual(
                        html.count(mensaje_prueba),
                        1,
                        f"El mensaje se duplicó o no apareció en {ruta} ({rol.nombre})",
                    )

    def test_mensaje_sale_una_vez_en_las_pantallas_de_parametrizacion(self):
        # Estas pantallas no están en el menú de R9 y heredan de _pagina.html.
        rol = Rol.objects.get(nombre="Administrador")
        usuario = self._crear_usuario_para_rol(rol, 30)
        self.client.force_login(usuario)
        mensaje = "No hubo cambios que guardar."
        for nombre in ("periodos", "facultades_carreras", "documentos", "alertas", "estados"):
            with self.subTest(pantalla=nombre):
                self._inyectar_mensaje_en_sesion(mensaje)
                resp = self.client.get(reverse(f"parametrizacion:{nombre}"))
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.content.decode("utf-8").count(mensaje), 1)

    def test_pagina_403_con_sesion_carga_sistra_css_y_un_solo_logout(self):
        rol_estudiante = Rol.objects.get(nombre="Estudiante")
        estudiante = self._crear_usuario_para_rol(rol_estudiante, 40)
        self.client.force_login(estudiante)

        resp = self.client.get(reverse("informes:aprobacion"))
        self.assertEqual(resp.status_code, 403)
        html = resp.content.decode("utf-8")

        self.assertIn("css/sistra.css", html)
        self.assertEqual(html.count(f'action="{self.logout_url}"'), 1)
