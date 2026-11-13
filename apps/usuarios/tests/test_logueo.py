"""SISTRA-13 · Pruebas del login, cambio y recuperación de contraseña."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import SESSION_KEY, get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.personas.models import Director, Estudiante
from apps.seguimiento.models import Auditoria
from apps.usuarios.forms.logueo import (
    CambiarContrasenaForm,
    LoginForm,
    RecuperarContrasenaForm,
)
from apps.usuarios.models import Estado, Rol
from apps.usuarios.views.logueo import (
    DURACION_BLOQUEO,
    ERROR_CREDENCIALES,
    MENSAJE_BLOQUEO,
    MENSAJE_CAMBIO_INVALIDO,
    MENSAJE_CAMBIO_OK,
    MENSAJE_INACTIVO,
    MENSAJE_RECUPERACION,
    _HASH_CONTRASENA_RELLENO,
    _clave_cache_recuperacion,
)

CONTRASENA_PRUEBA = 'PruebaSegura-2026!'
CONTRASENA_NUEVA = 'Nueva-Segura-2026!'
CORREO_PRUEBA = 'estudiante1@unipamplona.edu.co'


class LoginTests(TestCase):
    def setUp(self):
        # Los roles base los crea la migración 0002; no deben duplicarse en setUp.
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.rol_director = Rol.objects.get(nombre='Director')
        self.rol_administrador = Rol.objects.get(nombre='Administrador')
        self.usuario = self.crear_usuario(
            correo=CORREO_PRUEBA,
            nombre='Estudiante Prueba Uno',
            cedula='1000000001',
            nombre_usuario='estudiante1',
            rol=self.rol_estudiante,
        )
        self.perfil = Estudiante.objects.create(usuario=self.usuario)
        self.url_login = reverse('usuarios:login')
        self.url_inicio_estudiante = reverse('usuarios:inicio_estudiante')
        self.url_inicio_director = reverse('usuarios:inicio_director')
        self.url_inicio_administrador = reverse('usuarios:inicio_administrador')
        self.url_cambio = reverse('usuarios:cambiar_contrasena')
        self.url_recuperacion = reverse('usuarios:recuperar_contrasena')
        self.url_logout = reverse('usuarios:logout')
        cache.delete(_clave_cache_recuperacion(CORREO_PRUEBA))

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
        requiere_cambio_contrasena=False,
    ):
        Usuario = get_user_model()
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password=password,
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=nombre_usuario,
            rol=rol or self.rol_estudiante,
            estado=estado,
            requiere_cambio_contrasena=requiere_cambio_contrasena,
        )

    def enviar_login(self, correo=CORREO_PRUEBA, contrasena=CONTRASENA_PRUEBA, next_url=None):
        datos = {'correo': correo, 'contrasena': contrasena}
        if next_url is not None:
            datos['next'] = next_url
        return self.client.post(self.url_login, datos)

    def test_roles_base_se_obtienen_de_la_migracion_y_no_se_vuelven_a_crear(self):
        self.assertEqual(Rol.objects.filter(nombre='Estudiante').count(), 1)
        self.assertEqual(Rol.objects.filter(nombre='Director').count(), 1)
        self.assertEqual(Rol.objects.filter(nombre='Administrador').count(), 1)

    def test_pantalla_login_renderiza_campos_csrf_y_no_ofrece_auto_registro(self):
        response = self.client.get(self.url_login)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="correo"')
        self.assertContains(response, 'name="contrasena"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'Estudiante, Director o ADMO')
        self.assertContains(response, '¿Olvidaste tu contraseña?')
        self.assertNotContains(response, 'Registrar una cuenta')
        self.assertIn('no-store', response['Cache-Control'])

    def test_formulario_login_rechaza_gmail_sin_consultar_base_de_datos(self):
        form = LoginForm({'correo': 'persona@gmail.com', 'contrasena': 'cualquier cosa'})
        with self.assertNumQueries(0):
            self.assertFalse(form.is_valid())
        self.assertIn('unipamplona.edu.co', str(form.errors['correo']))

    def test_formulario_recuperacion_rechaza_dominio_institucional_falso(self):
        form = RecuperarContrasenaForm({'correo': 'persona@unipamplona.edu.co.ejemplo.com'})
        self.assertFalse(form.is_valid())
        self.assertIn('correo', form.errors)

    def test_formulario_normaliza_correo_institucional_en_mayusculas(self):
        form = LoginForm(
            {
                'correo': '  ESTUDIANTE1@UNIPAMPLONA.EDU.CO  ',
                'contrasena': CONTRASENA_PRUEBA,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['correo'], CORREO_PRUEBA)

    def test_usuario_inexistente_recibe_mensaje_generico_y_hash_relleno(self):
        with patch('apps.usuarios.views.logueo.check_password', return_value=False) as check:
            response = self.enviar_login('no-existe@unipamplona.edu.co')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)
        check.assert_called_once_with(CONTRASENA_PRUEBA, _HASH_CONTRASENA_RELLENO)
        auditoria = Auditoria.objects.get(accion='Iniciar sesión')
        self.assertIsNone(auditoria.usuario)
        self.assertEqual(auditoria.resultado, 'Fallo')

    def test_estudiante_sin_perfil_usa_hash_relleno_y_no_inicia_sesion(self):
        sin_perfil = self.crear_usuario(
            correo='sin.perfil@unipamplona.edu.co',
            nombre='Sin Perfil',
            cedula='1000000003',
            nombre_usuario='sin_perfil',
        )
        with patch('apps.usuarios.views.logueo.check_password', return_value=False) as check:
            response = self.enviar_login(sin_perfil.correo_institucional)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)
        check.assert_called_once_with(CONTRASENA_PRUEBA, _HASH_CONTRASENA_RELLENO)

    def test_login_estudiante_correcto_crea_sesion_y_audita_con_vocabulario_estandar(self):
        response = self.enviar_login(correo='ESTUDIANTE1@UNIPAMPLONA.EDU.CO')
        self.assertRedirects(response, self.url_inicio_estudiante)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.usuario.pk))
        self.usuario.refresh_from_db()
        self.assertIsNotNone(self.usuario.last_login)
        self.assertEqual(self.usuario.intentos_fallidos, 0)
        self.assertIsNone(self.usuario.bloqueado_hasta)
        auditoria = Auditoria.objects.get(accion='Iniciar sesión', usuario=self.usuario)
        self.assertEqual(auditoria.resultado, 'Éxito')
        self.assertTrue(self.usuario.password.startswith('pbkdf2_sha256$'))

    def test_login_director_conduce_a_su_inicio(self):
        director = self.crear_usuario(
            correo='director@unipamplona.edu.co',
            nombre='Director Prueba',
            cedula='1000000004',
            nombre_usuario='director',
            rol=self.rol_director,
        )
        Director.objects.create(usuario=director)
        response = self.enviar_login(director.correo_institucional)
        self.assertRedirects(response, self.url_inicio_director)
        self.assertEqual(self.client.session[SESSION_KEY], str(director.pk))

    def test_login_admo_administrador_conduce_a_su_inicio(self):
        administrador = self.crear_usuario(
            correo='admo@unipamplona.edu.co',
            nombre='ADMO Prueba',
            cedula='1000000005',
            nombre_usuario='admo',
            rol=self.rol_administrador,
        )
        response = self.enviar_login(administrador.correo_institucional)
        self.assertRedirects(response, self.url_inicio_administrador)
        self.assertEqual(self.client.session[SESSION_KEY], str(administrador.pk))

    def test_director_sin_perfil_no_inicia_sesion_ni_omite_hash(self):
        director = self.crear_usuario(
            correo='sin.director@unipamplona.edu.co',
            nombre='Director sin perfil',
            cedula='1000000006',
            nombre_usuario='sin_director',
            rol=self.rol_director,
        )
        with patch('apps.usuarios.views.logueo.check_password', return_value=False) as check:
            response = self.enviar_login(director.correo_institucional)
        self.assertContains(response, ERROR_CREDENCIALES)
        self.assertNotIn(SESSION_KEY, self.client.session)
        check.assert_called_once_with(CONTRASENA_PRUEBA, _HASH_CONTRASENA_RELLENO)

    def test_usuario_inactivo_no_inicia_sesion_y_contrasena_valida_muestra_mensaje_brD(self):
        self.usuario.estado = Estado.INACTIVO
        self.usuario.save(update_fields=['estado'])
        response = self.enviar_login()
        self.assertContains(response, MENSAJE_INACTIVO)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(
            Auditoria.objects.get(accion='Iniciar sesión').resultado,
            'Fallo',
        )

    def test_usuario_inactivo_con_contrasena_incorrecta_recibe_mensaje_generico(self):
        self.usuario.estado = Estado.INACTIVO
        self.usuario.save(update_fields=['estado'])
        response = self.enviar_login(contrasena='Incorrecta-2026!')
        self.assertContains(response, ERROR_CREDENCIALES)

    def test_rol_inactivo_no_inicia_sesion(self):
        self.rol_estudiante.estado = Estado.INACTIVO
        self.rol_estudiante.save(update_fields=['estado'])
        response = self.enviar_login()
        self.assertContains(response, MENSAJE_INACTIVO)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_contrasena_incorrecta_incrementa_intentos_y_audita_fallo_sin_guardarla(self):
        response = self.enviar_login(contrasena='Contraseña equivocada')
        self.assertContains(response, ERROR_CREDENCIALES)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.intentos_fallidos, 1)
        self.assertIsNone(self.usuario.bloqueado_hasta)
        self.assertNotIn(SESSION_KEY, self.client.session)
        auditoria = Auditoria.objects.get(accion='Iniciar sesión', usuario=self.usuario)
        self.assertEqual(auditoria.resultado, 'Fallo')
        self.assertNotIn('Contraseña equivocada', auditoria.detalle)

    def test_quinto_fallo_bloquea_quince_minutos_reinicia_contador_y_audita(self):
        for _ in range(5):
            response = self.enviar_login(contrasena='Contraseña incorrecta')
            self.assertContains(response, ERROR_CREDENCIALES)

        ahora = timezone.now()
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.intentos_fallidos, 0)
        self.assertIsNotNone(self.usuario.bloqueado_hasta)
        self.assertGreater(self.usuario.bloqueado_hasta, ahora + timedelta(minutes=14))
        self.assertLessEqual(self.usuario.bloqueado_hasta, ahora + DURACION_BLOQUEO)
        auditoria_bloqueo = Auditoria.objects.get(accion='Bloquear cuenta')
        self.assertEqual(auditoria_bloqueo.resultado, 'Éxito')
        self.assertEqual(auditoria_bloqueo.usuario_id, self.usuario.pk)

    def test_cuenta_bloqueada_no_incrementa_contador_y_con_clave_correcta_muestra_aviso(self):
        self.usuario.bloqueado_hasta = timezone.now() + timedelta(minutes=5)
        self.usuario.save(update_fields=['bloqueado_hasta'])
        response = self.enviar_login()
        self.assertContains(response, MENSAJE_BLOQUEO)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.intentos_fallidos, 0)

    def test_cuenta_bloqueada_con_clave_incorrecta_recibe_error_generico(self):
        self.usuario.bloqueado_hasta = timezone.now() + timedelta(minutes=5)
        self.usuario.save(update_fields=['bloqueado_hasta'])
        response = self.enviar_login(contrasena='Incorrecta-2026!')
        self.assertContains(response, ERROR_CREDENCIALES)

    def test_bloqueo_vencido_se_limpia_y_permite_reintentar(self):
        self.usuario.bloqueado_hasta = timezone.now() - timedelta(seconds=1)
        self.usuario.save(update_fields=['bloqueado_hasta'])
        response = self.enviar_login(contrasena='Contraseña incorrecta')
        self.assertContains(response, ERROR_CREDENCIALES)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.intentos_fallidos, 1)
        self.assertIsNone(self.usuario.bloqueado_hasta)

    def test_login_respeta_next_local_seguro(self):
        destino = '/propuestas/mi-propuesta/'
        response = self.enviar_login(next_url=destino)
        self.assertRedirects(response, destino, fetch_redirect_response=False)

    def test_login_rechaza_next_externo_y_conserva_inicio_del_rol(self):
        response = self.enviar_login(next_url='https://sitio-malicioso.example/')
        self.assertRedirects(response, self.url_inicio_estudiante)

    def test_login_rechaza_next_protocol_relative(self):
        response = self.enviar_login(next_url='//evil.example/path')
        self.assertRedirects(response, self.url_inicio_estudiante)

    def test_usuario_con_cambio_obligatorio_no_llega_al_inicio_antes_de_cambiar(self):
        self.usuario.requiere_cambio_contrasena = True
        self.usuario.save(update_fields=['requiere_cambio_contrasena'])
        respuesta_login = self.enviar_login(next_url='/propuestas/mi-propuesta/')
        self.assertRedirects(respuesta_login, self.url_cambio)
        respuesta_inicio = self.client.get(self.url_inicio_estudiante)
        self.assertRedirects(respuesta_inicio, self.url_cambio)

    def test_admo_con_cambio_obligatorio_no_puede_abrir_roles_ni_gestion(self):
        administrador = self.crear_usuario(
            correo='admo-temporal@unipamplona.edu.co',
            nombre='ADMO con clave temporal',
            cedula='1000000010',
            nombre_usuario='admo_temporal',
            rol=self.rol_administrador,
            requiere_cambio_contrasena=True,
        )
        respuesta_login = self.enviar_login(
            correo=administrador.correo_institucional,
            contrasena=CONTRASENA_PRUEBA,
        )
        self.assertRedirects(respuesta_login, self.url_cambio)

        for ruta in ('/usuarios/roles/', '/usuarios/gestion/'):
            with self.subTest(ruta=ruta):
                respuesta = self.client.get(ruta)
                self.assertRedirects(
                    respuesta,
                    self.url_cambio,
                    fetch_redirect_response=False,
                )

        respuesta_static = self.client.get('/static/usuarios/css/logueo.css')
        self.assertNotEqual(respuesta_static.status_code, 302)

    def test_cambio_obligatorio_guarda_hash_quita_bandera_y_reanuda_next_seguro(self):
        self.usuario.requiere_cambio_contrasena = True
        self.usuario.save(update_fields=['requiere_cambio_contrasena'])
        self.enviar_login(next_url='/propuestas/mi-propuesta/')
        respuesta = self.client.post(
            self.url_cambio,
            {
                'contrasena_actual': CONTRASENA_PRUEBA,
                'contrasena_nueva': CONTRASENA_NUEVA,
                'confirmar_contrasena': CONTRASENA_NUEVA,
                'next': 'https://externo.example/',
            },
        )
        self.assertRedirects(respuesta, '/propuestas/mi-propuesta/', fetch_redirect_response=False)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.requiere_cambio_contrasena)
        self.assertTrue(self.usuario.check_password(CONTRASENA_NUEVA))
        self.assertTrue(self.usuario.password.startswith('pbkdf2_sha256$'))
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertEqual(
            Auditoria.objects.get(accion='Cambiar contraseña').resultado,
            'Éxito',
        )

    def test_pantalla_cambio_obligatorio_ofrece_logout_y_permite_cerrar_sesion(self):
        self.usuario.requiere_cambio_contrasena = True
        self.usuario.save(update_fields=['requiere_cambio_contrasena'])
        self.client.force_login(self.usuario)

        respuesta_pantalla = self.client.get(self.url_cambio)
        self.assertEqual(respuesta_pantalla.status_code, 200)
        self.assertContains(respuesta_pantalla, f'action="{self.url_logout}"')
        self.assertContains(respuesta_pantalla, 'Cerrar sesión')

        respuesta_logout = self.client.post(self.url_logout)
        self.assertRedirects(respuesta_logout, self.url_login)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_cambio_rechaza_contrasena_actual_incorrecta_o_confirmacion_distinta(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            self.url_cambio,
            {
                'contrasena_actual': 'Actual-incorrecta-2026!',
                'contrasena_nueva': CONTRASENA_NUEVA,
                'confirmar_contrasena': 'Otra-Nueva-2026!',
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, MENSAJE_CAMBIO_INVALIDO)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(CONTRASENA_PRUEBA))
        auditoria = Auditoria.objects.get(accion='Cambiar contraseña')
        self.assertEqual(auditoria.resultado, 'Fallo')

    def test_cambio_rechaza_contrasena_debil_segun_validadores_django(self):
        self.client.force_login(self.usuario)
        respuesta = self.client.post(
            self.url_cambio,
            {
                'contrasena_actual': CONTRASENA_PRUEBA,
                'contrasena_nueva': '123',
                'confirmar_contrasena': '123',
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, MENSAJE_CAMBIO_INVALIDO)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(CONTRASENA_PRUEBA))

    def test_forma_de_cambio_aplica_politica_y_rechaza_reutilizar_contrasena_temporal(self):
        form = CambiarContrasenaForm(
            {
                'contrasena_actual': CONTRASENA_PRUEBA,
                'contrasena_nueva': CONTRASENA_PRUEBA,
                'confirmar_contrasena': CONTRASENA_PRUEBA,
            },
            usuario=self.usuario,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('contrasena_nueva', form.errors)

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
        DEFAULT_FROM_EMAIL='SISTRA-UP <sistra@example.org>',
    )
    def test_recuperacion_envia_clave_temporal_marca_cambio_y_mensaje_generico(self):
        mail.outbox.clear()
        temporal = 'Temporal-Segura-2026!Az'
        with patch('apps.usuarios.views.logueo.get_random_string', return_value=temporal):
            respuesta = self.client.post(
                self.url_recuperacion,
                {'correo': self.usuario.correo_institucional},
                follow=True,
            )
        self.assertContains(respuesta, MENSAJE_RECUPERACION)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.usuario.correo_institucional])
        self.assertIn('contraseña temporal', mail.outbox[0].body.lower())
        self.assertIn(temporal, mail.outbox[0].body)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.requiere_cambio_contrasena)
        self.assertTrue(self.usuario.check_password(temporal))
        self.assertTrue(self.usuario.password.startswith('pbkdf2_sha256$'))
        auditoria = Auditoria.objects.get(accion='Recuperar contraseña')
        self.assertEqual(auditoria.resultado, 'Éxito')
        self.assertNotIn(temporal, auditoria.detalle)

        respuesta_login = self.enviar_login(contrasena=temporal)
        self.assertRedirects(respuesta_login, self.url_cambio)

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
        DEFAULT_FROM_EMAIL='SISTRA-UP <sistra@example.org>',
    )
    def test_correo_inexistente_muestra_el_mismo_mensaje_y_no_envia(self):
        mail.outbox.clear()
        respuesta = self.client.post(
            self.url_recuperacion,
            {'correo': 'no-existe@unipamplona.edu.co'},
            follow=True,
        )
        self.assertContains(respuesta, MENSAJE_RECUPERACION)
        self.assertEqual(mail.outbox, [])
        auditoria = Auditoria.objects.get(accion='Recuperar contraseña')
        self.assertIsNone(auditoria.usuario)
        self.assertEqual(auditoria.resultado, 'Fallo')

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
        DEFAULT_FROM_EMAIL='SISTRA-UP <sistra@example.org>',
    )
    def test_recuperacion_limita_a_una_solicitud_por_correo_durante_cinco_minutos(self):
        mail.outbox.clear()
        cache.delete(_clave_cache_recuperacion(self.usuario.correo_institucional))
        datos = {'correo': self.usuario.correo_institucional}

        primera = self.client.post(self.url_recuperacion, datos, follow=True)
        self.assertContains(primera, MENSAJE_RECUPERACION)
        self.usuario.refresh_from_db()
        hash_despues_de_primera = self.usuario.password
        self.assertEqual(len(mail.outbox), 1)

        segunda = self.client.post(self.url_recuperacion, datos, follow=True)
        self.assertContains(segunda, MENSAJE_RECUPERACION)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, hash_despues_de_primera)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
        DEFAULT_FROM_EMAIL='SISTRA-UP <sistra@example.org>',
    )
    def test_usuario_inactivo_recibe_mensaje_generico_y_no_se_cambia_su_clave(self):
        self.usuario.estado = Estado.INACTIVO
        self.usuario.save(update_fields=['estado'])
        hash_anterior = self.usuario.password
        mail.outbox.clear()
        respuesta = self.client.post(
            self.url_recuperacion,
            {'correo': self.usuario.correo_institucional},
            follow=True,
        )
        self.assertContains(respuesta, MENSAJE_RECUPERACION)
        self.assertEqual(mail.outbox, [])
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, hash_anterior)

    @override_settings(
        MAILERS={'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}},
        DEFAULT_FROM_EMAIL='SISTRA-UP <sistra@example.org>',
    )
    def test_fallo_de_correo_no_cambia_la_contrasena_y_no_revela_la_cuenta(self):
        hash_anterior = self.usuario.password
        with patch('apps.usuarios.views.logueo.send_mail', side_effect=OSError('SMTP caído')):
            respuesta = self.client.post(
                self.url_recuperacion,
                {'correo': self.usuario.correo_institucional},
                follow=True,
            )
        self.assertContains(respuesta, MENSAJE_RECUPERACION)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.password, hash_anterior)
        self.assertFalse(self.usuario.requiere_cambio_contrasena)
        self.assertEqual(
            Auditoria.objects.get(accion='Recuperar contraseña').resultado,
            'Fallo',
        )

    def test_login_required_usa_login_url_global(self):
        respuesta = self.client.get(self.url_inicio_estudiante)
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta['Location'].startswith(self.url_login))

    def test_inicio_de_cada_rol_es_solo_para_el_rol_correcto(self):
        director = self.crear_usuario(
            correo='director@unipamplona.edu.co',
            nombre='Director Prueba',
            cedula='1000000007',
            nombre_usuario='director',
            rol=self.rol_director,
        )
        Director.objects.create(usuario=director)
        self.client.force_login(director)
        respuesta = self.client.get(self.url_inicio_estudiante)
        self.assertRedirects(respuesta, self.url_inicio_director)
        self.assertEqual(self.client.get(self.url_inicio_director).status_code, 200)

    def test_logout_audita_cierre_y_finaliza_sesion(self):
        self.enviar_login()
        self.assertIn(SESSION_KEY, self.client.session)
        respuesta = self.client.post(self.url_logout)
        self.assertRedirects(respuesta, self.url_login)
        self.assertNotIn(SESSION_KEY, self.client.session)
        auditoria = Auditoria.objects.get(accion='Cerrar sesión')
        self.assertEqual(auditoria.usuario_id, self.usuario.pk)
        self.assertEqual(auditoria.resultado, 'Éxito')

    def test_logout_exige_post_y_csrf(self):
        cliente_seguro = Client(enforce_csrf_checks=True)
        cliente_seguro.force_login(self.usuario)
        respuesta_get = cliente_seguro.get(self.url_logout)
        self.assertEqual(respuesta_get.status_code, 405)

        respuesta_sin_csrf = cliente_seguro.post(self.url_logout)
        self.assertEqual(respuesta_sin_csrf.status_code, 403)
        self.assertIn(SESSION_KEY, cliente_seguro.session)

        cliente_seguro.get(self.url_inicio_estudiante)
        token_csrf = cliente_seguro.cookies['csrftoken'].value
        respuesta_logout = cliente_seguro.post(
            self.url_logout,
            {'csrfmiddlewaretoken': token_csrf},
            HTTP_X_CSRFTOKEN=token_csrf,
        )
        self.assertRedirects(respuesta_logout, self.url_login)
        self.assertNotIn(SESSION_KEY, cliente_seguro.session)
