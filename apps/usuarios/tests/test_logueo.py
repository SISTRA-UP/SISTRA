"""SISTRA-13 · Pruebas del login institucional de estudiantes."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.personas.models import Director, Estudiante
from apps.usuarios.forms.logueo import LoginEstudianteForm
from apps.usuarios.models import Estado, Rol
from apps.usuarios.views.logueo import ERROR_CREDENCIALES
from apps.seguimiento.models import Auditoria


CONTRASENA_PRUEBA = 'PruebaSegura-2026!'


class LoginEstudianteTests(TestCase):
    def setUp(self):
        self.rol_estudiante = Rol.objects.create(
            nombre='Estudiante', estado=Estado.ACTIVO
        )
        self.usuario = self.crear_usuario(
            correo='estudiante1@unipamplona.edu.co',
            nombre='Estudiante Prueba Uno',
            cedula='1000000001',
            nombre_usuario='estudiante1',
            rol=self.rol_estudiante,
        )
        self.perfil = Estudiante.objects.create(usuario=self.usuario)
        self.url_login = reverse('usuarios:login_estudiante')
        self.url_inicio = reverse('usuarios:inicio_estudiante')
        self.url_logout = reverse('usuarios:logout_estudiante')

    def crear_usuario(
        self,
        *,
        correo,
        nombre,
        cedula,
        nombre_usuario,
        rol=None,
        estado=Estado.ACTIVO,
        password=CONTRASENA_PRUEBA,
    ):
        Usuario = get_user_model()
        rol = rol or self.rol_estudiante
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password=password,
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=nombre_usuario,
            rol=rol,
            estado=estado,
            requiere_cambio_contrasena=False,
        )

    def enviar_login(self, correo, contrasena=CONTRASENA_PRUEBA):
        return self.client.post(
            self.url_login,
            {'correo': correo, 'contrasena': contrasena},
        )

    def test_pantalla_login_renderiza_campos_y_csrf_sin_registro_publico(self):
        response = self.client.get(self.url_login)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="correo"')
        self.assertContains(response, 'name="contrasena"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'Iniciar sesión')
        self.assertNotContains(response, 'Registrar una cuenta')

    def test_formulario_rechaza_gmail_sin_consultar_la_base_de_datos(self):
        form = LoginEstudianteForm(
            {'correo': 'persona@gmail.com', 'contrasena': 'cualquier cosa'}
        )
        with self.assertNumQueries(0):
            self.assertFalse(form.is_valid())
        self.assertIn('unipamplona.edu.co', str(form.errors['correo']))

    def test_formulario_rechaza_dominio_institucional_falso(self):
        form = LoginEstudianteForm(
            {'correo': 'persona@unipamplona.edu.co.ejemplo.com', 'contrasena': 'x'}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('correo', form.errors)

    def test_formulario_normaliza_correo_institucional_en_mayusculas(self):
        form = LoginEstudianteForm(
            {
                'correo': '  ESTUDIANTE1@UNIPAMPLONA.EDU.CO  ',
                'contrasena': CONTRASENA_PRUEBA,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data['correo'], 'estudiante1@unipamplona.edu.co'
        )

    def test_usuario_inexistente_recibe_mensaje_generico_y_no_inicia_sesion(self):
        response = self.enviar_login('no-existe@unipamplona.edu.co')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)
        auditoria = Auditoria.objects.get(accion='login_estudiante')
        self.assertIsNone(auditoria.usuario)
        self.assertEqual(auditoria.resultado, 'Fallido')

    def test_usuario_sin_perfil_estudiante_no_inicia_sesion(self):
        self.crear_usuario(
            correo='sin.perfil@unipamplona.edu.co',
            nombre='Sin Perfil',
            cedula='1000000003',
            nombre_usuario='sin_perfil',
        )
        response = self.enviar_login('sin.perfil@unipamplona.edu.co')
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_usuario_inactivo_no_inicia_sesion(self):
        self.usuario.estado = Estado.INACTIVO
        self.usuario.save(update_fields=['estado'])
        response = self.enviar_login(self.usuario.correo_institucional)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_rol_inactivo_no_inicia_sesion(self):
        self.rol_estudiante.estado = Estado.INACTIVO
        self.rol_estudiante.save(update_fields=['estado'])
        response = self.enviar_login(self.usuario.correo_institucional)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_usuario_director_no_puede_entrar_por_el_login_de_estudiantes(self):
        rol_director = Rol.objects.create(nombre='Director', estado=Estado.ACTIVO)
        director = self.crear_usuario(
            correo='director@unipamplona.edu.co',
            nombre='Director Prueba',
            cedula='1000000004',
            nombre_usuario='director',
            rol=rol_director,
        )
        Director.objects.create(usuario=director)
        response = self.enviar_login(director.correo_institucional)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_contrasena_incorrecta_es_generica_y_aumenta_intentos(self):
        response = self.enviar_login(
            self.usuario.correo_institucional, 'Contraseña equivocada'
        )
        self.assertContains(response, ERROR_CREDENCIALES)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.intentos_fallidos, 1)
        self.assertNotIn(SESSION_KEY, self.client.session)
        auditoria = Auditoria.objects.get(accion='login_estudiante')
        self.assertEqual(auditoria.usuario_id, self.usuario.pk)
        self.assertEqual(auditoria.resultado, 'Fallido')
        self.assertNotIn('Contraseña equivocada', auditoria.detalle)

    def test_cuenta_bloqueada_temporalmente_no_inicia_sesion(self):
        self.usuario.bloqueado_hasta = timezone.now() + timedelta(minutes=5)
        self.usuario.save(update_fields=['bloqueado_hasta'])
        response = self.enviar_login(self.usuario.correo_institucional)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_correcto_con_mayusculas_crea_sesion_y_actualiza_ultimo_ingreso(self):
        response = self.enviar_login('ESTUDIANTE1@UNIPAMPLONA.EDU.CO')
        self.assertRedirects(response, self.url_inicio)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.usuario.pk))
        self.usuario.refresh_from_db()
        self.assertIsNotNone(self.usuario.last_login)
        self.assertEqual(self.usuario.intentos_fallidos, 0)
        self.assertIsNone(self.usuario.bloqueado_hasta)
        auditoria = Auditoria.objects.get(accion='login_estudiante')
        self.assertEqual(auditoria.usuario_id, self.usuario.pk)
        self.assertEqual(auditoria.resultado, 'Exitoso')

    def test_contrasena_se_guarda_con_hash_de_django(self):
        self.assertNotEqual(self.usuario.password, CONTRASENA_PRUEBA)
        self.assertTrue(self.usuario.check_password(CONTRASENA_PRUEBA))

    def test_pagina_privada_exige_sesion_y_perfil_estudiante(self):
        response_anonimo = self.client.get(self.url_inicio)
        self.assertEqual(response_anonimo.status_code, 302)
        self.assertIn(self.url_login, response_anonimo['Location'])

        self.enviar_login(self.usuario.correo_institucional)
        response_autenticado = self.client.get(self.url_inicio)
        self.assertEqual(response_autenticado.status_code, 200)
        self.assertContains(response_autenticado, 'Esta pantalla es temporal')

    def test_logout_cierra_la_sesion(self):
        self.enviar_login(self.usuario.correo_institucional)
        self.assertIn(SESSION_KEY, self.client.session)
        response = self.client.post(self.url_logout)
        self.assertRedirects(response, self.url_login)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_logout_exige_post_y_proteccion_csrf(self):
        cliente_seguro = Client(enforce_csrf_checks=True)
        cliente_seguro.force_login(self.usuario)
        respuesta_get = cliente_seguro.get(self.url_logout)
        self.assertEqual(respuesta_get.status_code, 405)

        respuesta_sin_csrf = cliente_seguro.post(self.url_logout)
        self.assertEqual(respuesta_sin_csrf.status_code, 403)
        self.assertIn(SESSION_KEY, cliente_seguro.session)

        cliente_seguro.get(self.url_inicio)
        token_csrf = cliente_seguro.cookies['csrftoken'].value
        respuesta_logout = cliente_seguro.post(
            self.url_logout,
            {'csrfmiddlewaretoken': token_csrf},
            HTTP_X_CSRFTOKEN=token_csrf,
        )
        self.assertRedirects(respuesta_logout, self.url_login)
        self.assertNotIn(SESSION_KEY, cliente_seguro.session)

    def test_comando_crea_dos_cuentas_de_prueba_idempotentes(self):
        contrasena_demo = 'DemoSegura-2026!'
        with patch(
            'apps.usuarios.management.commands.crear_estudiantes_prueba.getpass',
            side_effect=[contrasena_demo, contrasena_demo],
        ) as pedir_contrasena:
            call_command('crear_estudiantes_prueba', stdout=StringIO())
        self.assertEqual(pedir_contrasena.call_count, 2)

        Usuario = get_user_model()
        segundo = Usuario.objects.get(
            correo_institucional='estudiante2@unipamplona.edu.co'
        )
        self.assertTrue(segundo.check_password(contrasena_demo))
        self.assertTrue(Estudiante.objects.filter(usuario=segundo).exists())

        with patch(
            'apps.usuarios.management.commands.crear_estudiantes_prueba.getpass'
        ) as pedir_contrasena_otra_vez:
            call_command('crear_estudiantes_prueba', stdout=StringIO())
        pedir_contrasena_otra_vez.assert_not_called()
        self.assertTrue(segundo.check_password(contrasena_demo))
        self.assertTrue(self.usuario.check_password(CONTRASENA_PRUEBA))
