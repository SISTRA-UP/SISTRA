"""SISTRA-10 · Roles (roles, permisos y usuarios): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

import threading
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import ProtectedError
from django.template.loader import render_to_string
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from django.test.utils import CaptureQueriesContext
from django.urls import path, reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.seguimiento.models import Auditoria
from apps.usuarios.forms.roles import UsuarioForm
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso

Usuario = get_user_model()

PERMISOS_DE_SISTRA_10 = [
    'rol.ver',
    'rol.crear',
    'rol.editar',
    'rol.inactivar',
    'rol.asignar_permisos',
    'usuario.ver',
    'usuario.inactivar',
    # Añadidos por la migración 0003, con los criterios nuevos de SIS-18.
    'usuario.crear',
    'usuario.editar',
    'usuario.eliminar',
]


class BaseRoles(TestCase):
    """Datos comunes. Los roles base y los permisos los siembra la migración 0002."""

    def setUp(self):
        self.rol_administrador = Rol.objects.get(nombre='Administrador')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.administrador = self.crear_usuario(
            'admin@unipamplona.edu.co', nombre='Ana Admin', cedula='1000000001'
        )

    def crear_usuario(self, correo, nombre='Persona de prueba', cedula='1000000000', rol=None):
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password='ClaveDePrueba123',
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=correo.split('@')[0],
            rol=rol or self.rol_administrador,
            requiere_cambio_contrasena=False,
        )

    def crear_rol_con(self, nombre, *permisos):
        """Un rol con solo esos permisos, para probar cada guarda por separado."""
        rol = Rol.objects.create(nombre=nombre)
        for permiso in Permiso.objects.filter(nombre__in=permisos):
            RolPermiso.objects.create(rol=rol, permiso=permiso)
        return rol

    def crear_carrera(self, nombre='Ingeniería Civil', codigo='IC-99'):
        facultad, _ = Facultad.objects.get_or_create(nombre='Facultad de Prueba')
        return Carrera.objects.create(facultad=facultad, nombre=nombre, codigo=codigo)

    def inscribir_en_carrera(self, usuario, nombre_carrera, codigo_carrera):
        """Deja al usuario como estudiante inscrito en una carrera."""
        carrera = self.crear_carrera(nombre_carrera, codigo_carrera)
        estudiante = Estudiante.objects.create(usuario=usuario)
        return EstudianteCarrera.objects.create(
            estudiante=estudiante, carrera=carrera, estado=EstadoInscripcion.ACTIVO
        )


class ReenvioDeCredencialesDelAdmo(BaseRoles):
    """SIS-72 · R5 · la acción «Reenviar» que el MSG-10-08 prometía y no existía.

    Cuando el correo de credenciales no sale, la cuenta queda creada y nadie
    conoce la contraseña temporal: solo existía en ese correo. Por eso reenviar
    no es volver a mandar lo mismo, es **generar otra**.
    """

    CLAVE = 'ClaveReenviadaDePrueba'

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.url_lista = reverse('usuarios:usuarios')
        self.sin_entrar = self.crear_usuario(
            'nelly.rios@unipamplona.edu.co', nombre='Nelly Ríos', cedula='1020304051'
        )
        self.sin_entrar.requiere_cambio_contrasena = True
        self.sin_entrar.save(update_fields=['requiere_cambio_contrasena'])
        mail.outbox.clear()

    def url_reenviar(self, usuario):
        return reverse('usuarios:usuario_reenviar', args=[usuario.pk])

    def reenviar(self, usuario):
        return self.client.post(self.url_reenviar(usuario), follow=True)

    def auditorias(self):
        return Auditoria.objects.filter(accion='Reenviar credenciales')

    # --- C1 · a quién se le ofrece el botón ---

    def test_la_lista_ofrece_el_boton_a_quien_tiene_contrasena_temporal(self):
        respuesta = self.client.get(self.url_lista)
        self.assertContains(respuesta, 'Reenviar credenciales')
        self.assertContains(respuesta, self.url_reenviar(self.sin_entrar))

    def test_la_lista_no_ofrece_el_boton_a_quien_ya_cambio_su_contrasena(self):
        # `self.administrador` se crea con la bandera en falso.
        self.sin_entrar.delete()
        respuesta = self.client.get(self.url_lista)
        self.assertNotContains(respuesta, 'Reenviar credenciales')

    def test_no_se_puede_reenviar_ni_a_mano_ni_sobre_la_propia_cuenta(self):
        # Dos cosas a la vez: la regla no puede vivir solo en la plantilla, y
        # `self.administrador` **es** la cuenta con la que se navega. No hace
        # falta una guarda de «no sobre mí mismo» como en Inactivar o Eliminar:
        # el middleware obliga a cambiar la contraseña temporal antes de poder
        # llegar aquí, así que quien navega siempre tiene la bandera en falso y
        # el filtro de la consulta ya lo deja fuera.
        respuesta = self.client.post(self.url_reenviar(self.administrador))
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(len(mail.outbox), 0)

    # --- C2 y C9 · la contraseña nueva llega y sirve ---

    def test_el_reenvio_manda_una_contrasena_nueva_que_funciona(self):
        anterior = self.sin_entrar.password
        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value=self.CLAVE,
        ):
            respuesta = self.reenviar(self.sin_entrar)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.CLAVE, mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, [self.sin_entrar.correo_institucional])

        self.sin_entrar.refresh_from_db()
        # Sirve para entrar, y la de antes ya no.
        self.assertTrue(self.sin_entrar.check_password(self.CLAVE))
        self.assertNotEqual(self.sin_entrar.password, anterior)
        self.assertFalse(self.sin_entrar.check_password('ClaveDePrueba123'))
        # Y sigue teniendo que cambiarla en el primer ingreso.
        self.assertTrue(self.sin_entrar.requiere_cambio_contrasena)

    def test_la_contrasena_nueva_no_se_guarda_en_claro_ni_se_audita(self):
        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value=self.CLAVE,
        ):
            self.reenviar(self.sin_entrar)

        self.sin_entrar.refresh_from_db()
        self.assertNotIn(self.CLAVE, self.sin_entrar.password)
        for registro in self.auditorias():
            self.assertNotIn(self.CLAVE, registro.detalle)

    # --- C3 · auditoría ---

    def test_el_reenvio_queda_auditado_con_exito(self):
        self.reenviar(self.sin_entrar)
        registro = self.auditorias().latest('id_auditoria')
        self.assertEqual(registro.resultado, 'Éxito')
        self.assertEqual(registro.tabla_afectada, 'usuario')
        self.assertEqual(registro.id_registro_afectado, self.sin_entrar.pk)
        self.assertEqual(registro.usuario, self.administrador)
        self.assertIn(self.sin_entrar.correo_institucional, registro.detalle)

    # --- C4 · si el correo falla ---

    def test_si_el_correo_falla_se_audita_fallo_y_se_avisa(self):
        anterior = self.sin_entrar.password
        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=OSError('servidor caído'),
        ):
            respuesta = self.reenviar(self.sin_entrar)

        self.assertEqual(len(mail.outbox), 0)
        registro = self.auditorias().latest('id_auditoria')
        self.assertEqual(registro.resultado, 'Fallo')
        self.assertContains(respuesta, 'alert-warning')

        # La cuenta no se rompe: la contraseña nueva quedó puesta y el botón sigue.
        self.sin_entrar.refresh_from_db()
        self.assertNotEqual(self.sin_entrar.password, anterior)
        self.assertTrue(self.sin_entrar.requiere_cambio_contrasena)
        self.assertContains(respuesta, self.url_reenviar(self.sin_entrar))

    # --- C1 de la revisión · la contraseña nueva tiene que servir de verdad ---

    def test_la_contrasena_nueva_sirve_para_entrar(self):
        # `check_password` no alcanza: el login exige además que la cuenta no
        # esté bloqueada. Esta prueba es la que caza ese caso.
        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value=self.CLAVE,
        ):
            self.reenviar(self.sin_entrar)

        self.client.logout()
        entro = self.client.login(
            correo_institucional=self.sin_entrar.correo_institucional,
            password=self.CLAVE,
        )
        self.assertTrue(entro)

    def test_reenviar_desbloquea_la_cuenta(self):
        # El caso típico de R5: no le llegó el correo, intentó a ciegas hasta
        # bloquearse y pidió ayuda. Si el reenvío no desbloquea, el ADMO le dice
        # que ya puede entrar y la cuenta lo sigue rechazando.
        self.sin_entrar.intentos_fallidos = 4
        self.sin_entrar.bloqueado_hasta = timezone.now() + timezone.timedelta(minutes=15)
        self.sin_entrar.save(
            update_fields=['intentos_fallidos', 'bloqueado_hasta']
        )

        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value=self.CLAVE,
        ):
            self.reenviar(self.sin_entrar)

        self.sin_entrar.refresh_from_db()
        self.assertIsNone(self.sin_entrar.bloqueado_hasta)
        self.assertEqual(self.sin_entrar.intentos_fallidos, 0)
        self.client.logout()
        self.assertTrue(
            self.client.login(
                correo_institucional=self.sin_entrar.correo_institucional,
                password=self.CLAVE,
            )
        )

    def test_la_llamada_pide_el_autor_por_nombre(self):
        # `enviar_credenciales(usuario, contrasena)` y
        # `reenviar_credenciales(usuario, autor=...)` son hermanas y contiguas:
        # si el autor fuera posicional, pasarle una contraseña por error se
        # auditaría sin autor y nadie se enteraría.
        from apps.personas.forms.registro_estudiantes import reenviar_credenciales

        with self.assertRaises(TypeError):
            reenviar_credenciales(self.sin_entrar, self.administrador)

    # --- C8 · la ruta es solo POST y exige permiso ---

    def test_la_ruta_no_responde_a_get(self):
        self.assertEqual(
            self.client.get(self.url_reenviar(self.sin_entrar)).status_code, 405
        )

    def test_sin_el_permiso_de_editar_usuarios_responde_403(self):
        rol = self.crear_rol_con('Solo ver usuarios', 'usuario.ver')
        mirona = self.crear_usuario(
            'olga.mira@unipamplona.edu.co', nombre='Olga Mira', cedula='1020304052', rol=rol
        )
        self.client.force_login(mirona)
        self.assertEqual(
            self.client.post(self.url_reenviar(self.sin_entrar)).status_code, 403
        )
        self.assertEqual(len(mail.outbox), 0)


def _vista_que_revienta(request):
    """Solo existe para probar el camino real del 500 (SIS-73 · R8).

    No hay ninguna vista del sistema que levante una excepción, y crear una
    estaría fuera de alcance. Parchear una existente no sirve: el `urls.py` ya
    guarda la referencia a la función. Así que la vista y su `urlconf` viven
    aquí, en las pruebas, y se aplican con `override_settings`.
    """
    raise RuntimeError('error de prueba para el 500')


# Tupla y no lista a propósito: `get_resolver` cachea por `urlconf` y exige que
# sea hashable.
URLCONF_QUE_REVIENTA = (path('revienta/', _vista_que_revienta),)


def _vista_sin_permiso(request):
    """Solo existe para probar que el 403 no filtra el texto de la excepción.

    Django mete la excepción en el contexto del 403, así que si alguien
    escribiera `{{ exception }}` en la plantilla, un detalle interno llegaría
    al navegador. `requiere_permiso` no sirve para comprobarlo: lanza el
    `PermissionDenied` sin mensaje. Lo pidió la revisión de la PR #50.
    """
    raise PermissionDenied('texto interno')


URLCONF_SIN_PERMISO = (path('sin-permiso/', _vista_sin_permiso),)


class PaginasDeError(BaseRoles):
    """SIS-73 · R8 · las cuatro páginas de error, en español.

    Antes no existía ninguna: con `DEBUG=False` salían las de Django, en inglés
    y sin el mensaje del BRD. El 403 es el que más importa porque lo produce
    `requiere_permiso`, el decorador de SISTRA-10, en todo el sistema.
    """

    # MSG-11-04 del BRD (p. 69, Tabla 38), con el objeto de la frase
    # generalizado: el mensaje está redactado para Parametrización y esta
    # página sale en cualquier pantalla.
    TITULO_403 = 'Sin permiso'
    TEXTO_403 = 'No tienes permiso para acceder a esta página.'

    def setUp(self):
        super().setUp()
        rol_pelado = self.crear_rol_con('Sin permisos de roles')
        self.colado = self.crear_usuario(
            'tito.cano@unipamplona.edu.co',
            nombre='Tito Cano',
            cedula='1020304060',
            rol=rol_pelado,
        )

    # --- C1 y C2 · el 403 con MSG-11-04 y el botón «Volver» ---

    @override_settings(DEBUG=False)
    def test_sin_permiso_sale_el_403_con_el_mensaje_del_brd(self):
        self.client.force_login(self.colado)
        respuesta = self.client.get(reverse('usuarios:roles'))

        self.assertEqual(respuesta.status_code, 403)
        self.assertContains(respuesta, self.TITULO_403, status_code=403)
        self.assertContains(respuesta, self.TEXTO_403, status_code=403)
        # Y ya no la de Django, que está en inglés.
        self.assertNotContains(respuesta, 'Forbidden', status_code=403)

    @override_settings(DEBUG=False)
    def test_el_403_trae_el_boton_volver(self):
        # «Volver» es la acción que el BRD asocia a MSG-11-04.
        self.client.force_login(self.colado)
        respuesta = self.client.get(reverse('usuarios:roles'))
        self.assertContains(respuesta, 'Volver', status_code=403)

    # --- C3 · la 404 en español ---

    @override_settings(DEBUG=False)
    def test_una_ruta_que_no_existe_sale_en_espanol(self):
        respuesta = self.client.get('/esta-ruta-no-existe-marcador-interno/')

        self.assertEqual(respuesta.status_code, 404)
        self.assertContains(respuesta, 'no encontrada', status_code=404)
        self.assertNotContains(respuesta, 'Not Found', status_code=404)
        self.assertNotContains(respuesta, 'Page not found', status_code=404)
        # `page_not_found` pasa `request_path` y `exception` al contexto, así
        # que el 404 es la única de las cuatro que recibe algo que elige
        # quien hace la petición. Si alguien imprimiera `{{ request_path }}`,
        # la página reflejaría la ruta pedida: esto lo fija.
        self.assertNotContains(respuesta, 'marcador-interno', status_code=404)

    # --- C4 · la de CSRF en español ---

    @override_settings(DEBUG=False)
    def test_un_post_sin_token_csrf_sale_en_espanol(self):
        # El fallo de CSRF lo decide el middleware, antes de la vista, así que
        # sirve cualquier ruta que acepte POST sin pedir sesión.
        estricto = Client(enforce_csrf_checks=True)
        respuesta = estricto.post(reverse('usuarios:login'), {})

        self.assertEqual(respuesta.status_code, 403)
        self.assertContains(respuesta, 'formulario', status_code=403)
        self.assertNotContains(respuesta, 'CSRF verification failed', status_code=403)
        self.assertNotContains(respuesta, 'Forbidden', status_code=403)

    # --- C5 · el camino real del 500 ---

    @override_settings(DEBUG=False, ROOT_URLCONF=URLCONF_QUE_REVIENTA)
    def test_el_500_sale_en_espanol(self):
        # Sin esto el cliente de pruebas vuelve a lanzar la excepción en vez de
        # dejar que Django renderice su página de error.
        self.client.raise_request_exception = False
        respuesta = self.client.get('/revienta/')

        self.assertEqual(respuesta.status_code, 500)
        self.assertContains(respuesta, 'Error del sistema', status_code=500)
        self.assertNotContains(respuesta, 'Server Error', status_code=500)

    # --- C12 · el texto de la excepción no llega a la página ---

    @override_settings(DEBUG=False, ROOT_URLCONF=URLCONF_SIN_PERMISO)
    def test_el_403_no_muestra_el_texto_de_la_excepcion(self):
        # `django/views/defaults.py` renderiza el 403 con
        # `context={'exception': str(exception)}`: el detalle interno está
        # disponible en la plantilla y basta un `{{ exception }}` para
        # publicarlo. Esta prueba fija que no se imprime.
        respuesta = self.client.get('/sin-permiso/')

        self.assertEqual(respuesta.status_code, 403)
        self.assertContains(respuesta, self.TITULO_403, status_code=403)
        self.assertNotContains(respuesta, 'texto interno', status_code=403)

    @override_settings(DEBUG=False, ROOT_URLCONF=URLCONF_QUE_REVIENTA)
    def test_el_500_no_muestra_el_texto_de_la_excepcion(self):
        # El 500 es el más delicado: el mensaje de la excepción puede traer
        # una consulta, una ruta del servidor o datos de la persona.
        self.client.raise_request_exception = False
        respuesta = self.client.get('/revienta/')

        self.assertEqual(respuesta.status_code, 500)
        self.assertContains(respuesta, 'Error del sistema', status_code=500)
        self.assertNotContains(
            respuesta, 'error de prueba para el 500', status_code=500
        )
        self.assertNotContains(respuesta, 'RuntimeError', status_code=500)
        self.assertNotContains(respuesta, 'Traceback', status_code=500)

    # --- C13 · «Volver» no puede caer en otro 403 ---

    def test_el_boton_volver_regresa_a_la_pagina_anterior(self):
        # `/` es `dashboard:inicio`, protegida con `dashboard.ver`, que solo
        # se siembra para los tres roles base: un rol creado a mano sin ese
        # permiso llegaba al 403, pulsaba «Volver» y recibía otro 403. La
        # revisión de la PR #50 pidió este comportamiento exacto: volver atrás
        # si hay historial y usar `/` solo si no lo hay.
        for plantilla in ('403.html', '404.html', '500.html', '403_csrf.html'):
            with self.subTest(plantilla=plantilla):
                html = render_to_string(plantilla)
                # Una sola cadena, y no tres fragmentos sueltos: así la
                # prueba amarra el atributo, el elemento que lo lleva y el
                # respaldo `/` juntos. Con fragmentos por separado, un
                # `data-algo` con ese texto en cualquier parte de la página
                # la dejaba verde con el botón muerto.
                self.assertIn(
                    'href="/" onclick="if (history.length > 1) '
                    '{ history.back(); return false; }"',
                    html,
                )

    # --- C6 · ninguna de las cuatro consulta la base ---

    def test_las_cuatro_paginas_no_consultan_la_base(self):
        # Es lo que la tarjeta exige del 500: si la página de error consultara
        # la base, fallaría justo cuando el error ES de la base. Vale para las
        # cuatro, así que se comprueba en las cuatro.
        for plantilla in ('403.html', '404.html', '500.html', '403_csrf.html'):
            with self.subTest(plantilla=plantilla):
                with self.assertNumQueries(0):
                    render_to_string(plantilla)

    def test_no_consultan_la_base_ni_con_usuario_en_el_contexto(self):
        # La de arriba renderiza **sin petición**, así que el menú por permisos
        # recibiría `None` y devolvería `[]` sin consultar: no cazaría un
        # `{% include %}` colado. Lo encontró la revisión y tenía razón. Esta sí
        # lo caza: con petición y usuario autenticado, incluir el menú consulta.
        # El 500 no entra porque su camino real renderiza sin petición
        # (`django/views/defaults.py`: `template.render()` a secas).
        peticion = RequestFactory().get('/')
        peticion.user = self.colado
        for plantilla in ('403.html', '404.html', '403_csrf.html'):
            with self.subTest(plantilla=plantilla):
                with self.assertNumQueries(0):
                    render_to_string(plantilla, request=peticion)

    # --- C7 y C8 · heredan de base.html y no traen estilos propios ---

    def test_las_cuatro_heredan_de_base_html(self):
        # Es la condición con la que se desbloqueó la tarjeta: solo llenan
        # `{% block contenido %}`, así que tomarán el diseño nuevo sin tocarlas.
        for plantilla in ('403.html', '404.html', '500.html', '403_csrf.html'):
            with self.subTest(plantilla=plantilla):
                html = render_to_string(plantilla)
                # El CSS de Bootstrap solo lo pone base.html.
                self.assertIn('bootstrap@5.3.3', html)
                self.assertIn('<html lang="es">', html)

    def test_las_cuatro_no_traen_estilos_propios(self):
        for plantilla in ('403.html', '404.html', '500.html', '403_csrf.html'):
            with self.subTest(plantilla=plantilla):
                html = render_to_string(plantilla)
                self.assertNotIn('<style', html)
                self.assertNotIn('style=', html)
                # Bootstrap se enlaza una sola vez, en base.html, y no se
                # añade ninguna otra hoja de estilos.
                self.assertEqual(html.count('bootstrap@5.3.3/dist/css'), 1)
                self.assertEqual(html.count('<link'), 1)


class SiembraDeRolesYPermisos(BaseRoles):
    """C0 · base para el resto: sin permisos sembrados no hay nada que asignar."""

    def test_existen_los_tres_roles_iniciales(self):
        # Regla de negocio §3.6: Estudiante, Director y Administrador.
        nombres = set(Rol.objects.values_list('nombre', flat=True))
        self.assertTrue({'Estudiante', 'Director', 'Administrador'}.issubset(nombres))

    def test_existe_el_catalogo_de_permisos_de_sistra_10(self):
        sembrados = set(Permiso.objects.values_list('nombre', flat=True))
        self.assertTrue(set(PERMISOS_DE_SISTRA_10).issubset(sembrados))

    def test_el_administrador_tiene_todos_los_permisos_de_sistra_10(self):
        for nombre in PERMISOS_DE_SISTRA_10:
            with self.subTest(permiso=nombre):
                self.assertTrue(self.administrador.has_perm(nombre))

    def test_el_estudiante_no_tiene_permisos_de_administracion(self):
        estudiante = self.crear_usuario(
            'pedro.perez@unipamplona.edu.co', cedula='1000000002', rol=self.rol_estudiante
        )
        self.assertFalse(estudiante.has_perm('rol.crear'))
        self.assertFalse(estudiante.has_perm('usuario.ver'))


class CrearRolConPermisos(BaseRoles):
    """C1 · El ADMO puede crear un rol y asignarle permisos; al recargar se conservan."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)

    def test_crea_el_rol_con_los_permisos_marcados(self):
        permisos = Permiso.objects.filter(nombre__in=['rol.ver', 'usuario.ver'])
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Secretaria',
                'descripcion': 'Consulta roles y usuarios',
                'estado': Estado.ACTIVO,
                'permisos': [p.pk for p in permisos],
            },
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))

        rol = Rol.objects.get(nombre='Secretaria')
        guardados = set(
            RolPermiso.objects.filter(rol=rol).values_list('permiso__nombre', flat=True)
        )
        self.assertEqual(guardados, {'rol.ver', 'usuario.ver'})

    def test_los_permisos_se_conservan_al_recargar_la_pantalla(self):
        permisos = Permiso.objects.filter(nombre__in=['rol.ver', 'usuario.ver'])
        self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Secretaria',
                'descripcion': '',
                'estado': Estado.ACTIVO,
                'permisos': [p.pk for p in permisos],
            },
        )
        rol = Rol.objects.get(nombre='Secretaria')

        # "Al guardar y recargar se conservan": se vuelve a pedir la pantalla de edición
        # y los permisos tienen que llegar marcados.
        respuesta = self.client.get(reverse('usuarios:rol_editar', args=[rol.pk]))
        self.assertEqual(respuesta.status_code, 200)
        marcados = set(respuesta.context['formulario']['permisos'].initial)
        self.assertEqual(marcados, {p.pk for p in permisos})

    def test_al_editar_se_quitan_los_permisos_desmarcados(self):
        rol = Rol.objects.create(nombre='Secretaria')
        todos = list(Permiso.objects.filter(nombre__in=['rol.ver', 'usuario.ver']))
        for permiso in todos:
            RolPermiso.objects.create(rol=rol, permiso=permiso)

        self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {
                'nombre': 'Secretaria',
                'descripcion': '',
                'estado': Estado.ACTIVO,
                'permisos': [todos[0].pk],
            },
        )
        guardados = set(RolPermiso.objects.filter(rol=rol).values_list('permiso_id', flat=True))
        self.assertEqual(guardados, {todos[0].pk})

    def test_no_se_repite_el_nombre_del_rol(self):
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {'nombre': 'Administrador', 'descripcion': '', 'estado': Estado.ACTIVO},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Rol.objects.filter(nombre='Administrador').count(), 1)

    def test_inactivar_un_rol_le_quita_los_permisos_a_sus_usuarios(self):
        rol = Rol.objects.create(nombre='Secretaria')
        RolPermiso.objects.create(rol=rol, permiso=Permiso.objects.get(nombre='rol.ver'))
        secretaria = self.crear_usuario(
            'sara.soto@unipamplona.edu.co', cedula='1000000003', rol=rol
        )
        self.assertTrue(secretaria.has_perm('rol.ver'))

        respuesta = self.client.post(reverse('usuarios:rol_estado', args=[rol.pk]))
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        rol.refresh_from_db()
        self.assertEqual(rol.estado, Estado.INACTIVO)

        # El modelo memoriza los permisos por instancia: se vuelve a leer de la base.
        self.assertFalse(Usuario.objects.get(pk=secretaria.pk).has_perm('rol.ver'))

    def test_sin_permiso_no_se_puede_crear_un_rol(self):
        self.client.force_login(
            self.crear_usuario(
                'luis.lopez@unipamplona.edu.co', cedula='1000000004', rol=self.rol_estudiante
            )
        )
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {'nombre': 'Intruso', 'descripcion': '', 'estado': Estado.ACTIVO},
        )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Rol.objects.filter(nombre='Intruso').exists())

    def test_la_pantalla_lista_los_roles_con_su_total_de_permisos(self):
        respuesta = self.client.get(reverse('usuarios:roles'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Administrador')
        self.assertContains(respuesta, 'Estudiante')
        administrador = next(
            rol for rol in respuesta.context['roles'] if rol.nombre == 'Administrador'
        )
        # >= porque otros tickets (SISTRA-11, etc.) siembran permisos adicionales
        self.assertGreaterEqual(administrador.total_permisos, len(PERMISOS_DE_SISTRA_10))

    def test_quien_no_ha_entrado_no_ve_los_roles(self):
        # Desde SIS-40 el anónimo va al login, no al 403: el 403 queda para
        # quien sí tiene sesión y le falta el permiso.
        self.client.logout()
        respuesta = self.client.get(reverse('usuarios:roles'))

        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.url.startswith(reverse('usuarios:login')))

    def test_con_rol_editar_pero_sin_rol_inactivar_no_se_cambia_el_estado(self):
        # `estado` no es campo del formulario a propósito: si lo fuera, este POST
        # inactivaría el rol sin tener `rol.inactivar`.
        editor = self.crear_rol_con('Editor', 'rol.ver', 'rol.editar')
        self.client.force_login(
            self.crear_usuario('eva.editora@unipamplona.edu.co', cedula='1000000011', rol=editor)
        )
        objetivo = Rol.objects.create(nombre='Secretaria')

        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[objetivo.pk]),
            {'nombre': 'Secretaria', 'descripcion': '', 'estado': Estado.INACTIVO},
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        objetivo.refresh_from_db()
        self.assertEqual(objetivo.estado, Estado.ACTIVO)

        # Y la vista dedicada sí le pide el permiso que no tiene.
        self.assertEqual(
            self.client.post(reverse('usuarios:rol_estado', args=[objetivo.pk])).status_code,
            403,
        )

    def test_sin_el_permiso_de_asignar_no_se_pueden_inyectar_permisos(self):
        creador = self.crear_rol_con('Creador', 'rol.ver', 'rol.crear')
        self.client.force_login(
            self.crear_usuario(
                'caro.creadora@unipamplona.edu.co', cedula='1000000012', rol=creador
            )
        )
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Secretaria',
                'descripcion': '',
                'permisos': [Permiso.objects.get(nombre='usuario.inactivar').pk],
            },
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        rol = Rol.objects.get(nombre='Secretaria')
        self.assertEqual(RolPermiso.objects.filter(rol=rol).count(), 0)

    def test_no_se_puede_inactivar_un_rol_base(self):
        # Inactivar `Administrador` le quitaría los permisos a todos los
        # administradores, incluido el de reactivarlo: el sistema queda sin salida.
        for nombre in ['Administrador', 'Director', 'Estudiante']:
            with self.subTest(rol=nombre):
                rol = Rol.objects.get(nombre=nombre)
                respuesta = self.client.post(reverse('usuarios:rol_estado', args=[rol.pk]))
                self.assertRedirects(respuesta, reverse('usuarios:roles'))
                rol.refresh_from_db()
                self.assertEqual(rol.estado, Estado.ACTIVO)
        self.assertTrue(
            Usuario.objects.get(pk=self.administrador.pk).has_perm('rol.inactivar')
        )

    def test_no_se_puede_renombrar_un_rol_base(self):
        # Renombrar `Administrador` rompería `Usuario.es_administrador` en silencio.
        rol = Rol.objects.get(nombre='Administrador')
        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {'nombre': 'Admin', 'descripcion': 'cambiado'},
        )
        self.assertEqual(respuesta.status_code, 200)
        rol.refresh_from_db()
        self.assertEqual(rol.nombre, 'Administrador')

    def test_a_un_rol_base_si_se_le_cambian_los_permisos(self):
        rol = Rol.objects.get(nombre='Director')
        permiso = Permiso.objects.get(nombre='usuario.ver')
        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {'nombre': 'Director', 'descripcion': 'Director de carrera', 'permisos': [permiso.pk]},
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        self.assertEqual(
            set(RolPermiso.objects.filter(rol=rol).values_list('permiso__nombre', flat=True)),
            {'usuario.ver'},
        )

    def test_la_pantalla_no_ofrece_inactivar_los_roles_base(self):
        respuesta = self.client.get(reverse('usuarios:roles'))
        base = {rol.nombre for rol in respuesta.context['roles'] if rol.es_base}
        self.assertEqual(base, {'Estudiante', 'Director', 'Administrador'})


class BuscarYFiltrarUsuarios(BaseRoles):
    """C2 · La búsqueda encuentra por nombre, código o carrera, y el filtro por rol funciona."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.estudiante = self.crear_usuario(
            'maria.gomez@unipamplona.edu.co',
            nombre='María Gómez',
            cedula='1098765432',
            rol=self.rol_estudiante,
        )
        self.inscribir_en_carrera(self.estudiante, 'Ingeniería de Sistemas', 'IS-01')

    def buscar(self, **parametros):
        respuesta = self.client.get(reverse('usuarios:usuarios'), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return list(respuesta.context['usuarios'])

    def test_busca_por_nombre(self):
        self.assertEqual(self.buscar(q='María'), [self.estudiante])

    def test_busca_sin_tildes_si_coincide_el_nombre_de_usuario(self):
        # 'Maria' no coincide con 'María' en el nombre, pero sí con 'maria.gomez'.
        self.assertEqual(self.buscar(q='Maria'), [self.estudiante])

    def test_la_busqueda_por_nombre_no_ignora_las_tildes(self):
        # Limitación conocida: `icontains` sobre PostgreSQL no normaliza tildes.
        # Queda anotada en DUDAS; se resolvería con la extensión `unaccent`.
        nunez = self.crear_usuario(
            'pedro.p@unipamplona.edu.co',
            nombre='Pedro Núñez',
            cedula='1000000055',
            rol=self.rol_estudiante,
        )
        self.assertEqual(self.buscar(q='Nunez'), [])
        self.assertEqual(self.buscar(q='Núñez'), [nunez])

    def test_busca_por_cedula(self):
        self.assertEqual(self.buscar(q='1098765432'), [self.estudiante])

    def test_busca_por_nombre_de_usuario(self):
        self.assertEqual(self.buscar(q='maria.gomez'), [self.estudiante])

    def test_busca_por_correo_institucional(self):
        self.assertEqual(self.buscar(q='maria.gomez@unipamplona.edu.co'), [self.estudiante])

    def test_busca_por_nombre_de_la_carrera(self):
        self.assertEqual(self.buscar(q='Ingeniería de Sistemas'), [self.estudiante])

    def test_busca_por_codigo_de_la_carrera(self):
        self.assertEqual(self.buscar(q='IS-01'), [self.estudiante])

    def test_no_repite_al_estudiante_inscrito_en_dos_carreras(self):
        facultad = Facultad.objects.get(nombre='Facultad de Prueba')
        segunda = Carrera.objects.create(
            facultad=facultad, nombre='Ingeniería Civil', codigo='IC-01'
        )
        EstudianteCarrera.objects.create(
            estudiante=self.estudiante.estudiante,
            carrera=segunda,
            estado=EstadoInscripcion.ACTIVO,
        )
        self.assertEqual(self.buscar(q='Ingeniería'), [self.estudiante])

    def test_filtra_por_rol(self):
        self.assertEqual(self.buscar(rol=self.rol_estudiante.pk), [self.estudiante])
        self.assertEqual(self.buscar(rol=self.rol_administrador.pk), [self.administrador])

    def test_la_busqueda_y_el_filtro_se_combinan(self):
        self.assertEqual(self.buscar(q='María', rol=self.rol_administrador.pk), [])

    def test_sin_criterios_muestra_todos(self):
        self.assertCountEqual(self.buscar(), [self.administrador, self.estudiante])

    def test_sin_permiso_no_se_ve_la_lista(self):
        self.client.force_login(self.estudiante)
        self.assertEqual(self.client.get(reverse('usuarios:usuarios')).status_code, 403)


class InactivarUsuarios(BaseRoles):
    """C3 · Un usuario con trámites no se puede eliminar, solo inactivar."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.estudiante = self.crear_usuario(
            'juan.ruiz@unipamplona.edu.co',
            nombre='Juan Ruiz',
            cedula='1012345678',
            rol=self.rol_estudiante,
        )
        self.inscripcion = self.inscribir_en_carrera(
            self.estudiante, 'Ingeniería de Sistemas', 'IS-01'
        )

    def crear_tramite(self):
        return ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.PENDIENTE,
        )

    def test_inactivar_deja_al_usuario_sin_acceso(self):
        self.crear_tramite()
        respuesta = self.client.post(
            reverse('usuarios:usuario_estado', args=[self.estudiante.pk])
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))

        self.estudiante.refresh_from_db()
        self.assertEqual(self.estudiante.estado, Estado.INACTIVO)
        self.assertFalse(self.estudiante.is_active)

    def test_se_puede_reactivar(self):
        self.estudiante.estado = Estado.INACTIVO
        self.estudiante.save(update_fields=['estado'])
        self.client.post(reverse('usuarios:usuario_estado', args=[self.estudiante.pk]))

        self.estudiante.refresh_from_db()
        self.assertEqual(self.estudiante.estado, Estado.ACTIVO)
        self.assertTrue(self.estudiante.is_active)

    def test_inactivar_no_borra_el_tramite(self):
        proceso = self.crear_tramite()
        self.client.post(reverse('usuarios:usuario_estado', args=[self.estudiante.pk]))
        self.assertTrue(ProcesoTrabajoSocial.objects.filter(pk=proceso.pk).exists())

    def test_la_pantalla_ofrece_inactivar(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Inactivar')

    def test_un_usuario_con_tramites_no_se_puede_eliminar(self):
        self.crear_tramite()
        with self.assertRaises(ProtectedError):
            self.estudiante.delete()
        self.assertTrue(Usuario.objects.filter(pk=self.estudiante.pk).exists())

    def test_sin_permiso_no_se_puede_inactivar(self):
        self.client.force_login(self.estudiante)
        respuesta = self.client.post(
            reverse('usuarios:usuario_estado', args=[self.administrador.pk])
        )
        self.assertEqual(respuesta.status_code, 403)
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.estado, Estado.ACTIVO)

    def test_el_administrador_no_se_puede_inactivar_a_si_mismo(self):
        respuesta = self.client.post(
            reverse('usuarios:usuario_estado', args=[self.administrador.pk])
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.estado, Estado.ACTIVO)


class CrearUsuarios(BaseRoles):
    """C5 · El ADMO crea usuarios; a los Directores les asigna su carrera."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.carrera = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')

    def datos(self, **cambios):
        datos = {
            'nombre': 'Laura Peña',
            'cedula': '1020304050',
            'correo_institucional': 'laura.pena@unipamplona.edu.co',
            'rol': self.rol_estudiante.pk,
            'carrera': '',
        }
        datos.update(cambios)
        return datos

    def crear(self, **cambios):
        return self.client.post(reverse('usuarios:usuario_nuevo'), self.datos(**cambios))

    def test_crea_el_usuario_con_sus_datos(self):
        respuesta = self.crear()
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre, 'Laura Peña')
        self.assertEqual(usuario.correo_institucional, 'laura.pena@unipamplona.edu.co')
        self.assertEqual(usuario.rol, self.rol_estudiante)
        self.assertEqual(usuario.estado, Estado.ACTIVO)

    def test_el_nombre_de_usuario_sale_del_correo(self):
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre_usuario, 'laura.pena')

    def test_si_el_nombre_de_usuario_ya_existe_se_le_agrega_un_numero(self):
        self.crear_usuario(
            'laura.pena@otrodominio.edu.co', nombre='Laura Homónima', cedula='9999999999'
        )
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre_usuario, 'laura.pena-2')

    def test_la_contrasena_queda_temporal_y_cifrada(self):
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertTrue(usuario.requiere_cambio_contrasena)
        # Guardada como hash de Django, nunca en texto plano (RG-12 / SEC-01).
        self.assertTrue(usuario.password.startswith('pbkdf2_'))

    def test_la_contrasena_temporal_no_se_muestra_en_pantalla(self):
        with patch(
            'apps.usuarios.forms.roles.get_random_string',
            return_value='ClaveTemporalDePrueba',
        ):
            respuesta = self.crear()
        seguir = self.client.get(respuesta.url)
        self.assertNotContains(seguir, 'ClaveTemporalDePrueba')

    def test_al_crear_un_director_se_le_asigna_su_carrera(self):
        respuesta = self.crear(rol=self.rol_director.pk, carrera=self.carrera.pk)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        usuario = Usuario.objects.get(cedula='1020304050')
        asignacion = DirectorCarrera.objects.get(director__usuario=usuario)
        self.assertEqual(asignacion.carrera, self.carrera)
        self.assertTrue(asignacion.activo)
        self.assertIsNone(asignacion.fecha_fin)

    def test_un_director_sin_carrera_no_se_crea(self):
        respuesta = self.crear(rol=self.rol_director.pk, carrera='')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFormError(
            respuesta.context['formulario'],
            'carrera',
            'Un Director necesita la carrera que va a dirigir.',
        )
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_una_carrera_no_puede_tener_dos_directores_activos(self):
        self.crear(rol=self.rol_director.pk, carrera=self.carrera.pk)
        respuesta = self.crear(
            nombre='Otro Director',
            cedula='2020202020',
            correo_institucional='otro.director@unipamplona.edu.co',
            rol=self.rol_director.pk,
            carrera=self.carrera.pk,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            DirectorCarrera.objects.filter(carrera=self.carrera, activo=True).count(), 1
        )
        self.assertFalse(Usuario.objects.filter(cedula='2020202020').exists())

    def test_la_carrera_solo_se_le_asigna_a_un_director(self):
        respuesta = self.crear(rol=self.rol_estudiante.pk, carrera=self.carrera.pk)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFormError(
            respuesta.context['formulario'],
            'carrera',
            'La carrera solo se le asigna a un Director.',
        )

    def test_no_se_repite_la_cedula(self):
        respuesta = self.crear(cedula=self.administrador.cedula)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(nombre='Laura Peña').exists())

    def test_el_formulario_no_pide_el_estado_ni_la_contrasena(self):
        respuesta = self.client.get(reverse('usuarios:usuario_nuevo'))
        campos = set(respuesta.context['formulario'].fields)
        self.assertEqual(
            campos, {'nombre', 'cedula', 'correo_institucional', 'rol', 'carrera'}
        )

    def test_sin_el_permiso_no_se_puede_crear(self):
        miron = self.crear_usuario(
            'solo.mira@unipamplona.edu.co',
            nombre='Solo Mira',
            cedula='3030303030',
            rol=self.crear_rol_con('Consulta', 'usuario.ver'),
        )
        self.client.force_login(miron)
        self.assertEqual(self.crear().status_code, 403)
        self.assertEqual(
            self.client.get(reverse('usuarios:usuario_nuevo')).status_code, 403
        )

    def test_la_pantalla_ofrece_el_boton_de_nuevo_usuario(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertContains(respuesta, reverse('usuarios:usuario_nuevo'))


class CorreoDeCredencialesDelAdmo(BaseRoles):
    """SIS-69 · B3 · el usuario que crea el ADMO recibe su contraseña (RG-09, RN-10-06)."""

    CLAVE = 'ClaveTemporalDePrueba'

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.carrera = self.crear_carrera('Trabajo Social', 'TS-01')
        mail.outbox.clear()

    def datos(self, **cambios):
        datos = {
            'nombre': 'Diana Directora',
            'cedula': '1020304050',
            'correo_institucional': 'diana.directora@unipamplona.edu.co',
            'rol': self.rol_director.pk,
            'carrera': self.carrera.pk,
        }
        datos.update(cambios)
        return datos

    def crear(self, **cambios):
        seguir = cambios.pop('follow', False)
        return self.client.post(
            reverse('usuarios:usuario_nuevo'), self.datos(**cambios), follow=seguir
        )

    def crear_con_clave_conocida(self, **cambios):
        with patch(
            'apps.usuarios.forms.roles.get_random_string', return_value=self.CLAVE
        ):
            return self.crear(**cambios)

    def ultimo_envio(self):
        return Auditoria.objects.filter(accion='Enviar credenciales').latest(
            'id_auditoria'
        )

    def test_el_formulario_guarda_la_contrasena_temporal_al_crear(self):
        formulario = UsuarioForm(data=self.datos())
        self.assertTrue(formulario.is_valid(), formulario.errors)
        usuario = formulario.save()
        self.assertIsNotNone(formulario.contrasena_temporal)
        # Es la contraseña real de la cuenta, no una cadena cualquiera.
        self.assertTrue(usuario.check_password(formulario.contrasena_temporal))

    def test_al_editar_no_hay_contrasena_temporal(self):
        formulario = UsuarioForm(
            data={
                'nombre': 'Ana Corregida',
                'cedula': self.administrador.cedula,
                'correo_institucional': self.administrador.correo_institucional,
                'rol': self.rol_administrador.pk,
                'carrera': '',
            },
            instance=self.administrador,
        )
        self.assertTrue(formulario.is_valid(), formulario.errors)
        formulario.save()
        self.assertIsNone(formulario.contrasena_temporal)

    def test_se_manda_un_correo_al_usuario_nuevo(self):
        self.crear()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['diana.directora@unipamplona.edu.co'])

    def test_el_correo_lleva_el_usuario_de_ingreso_y_la_contrasena(self):
        self.crear_con_clave_conocida()
        cuerpo = mail.outbox[0].body
        self.assertIn('diana.directora@unipamplona.edu.co', cuerpo)
        self.assertIn(self.CLAVE, cuerpo)

    def test_con_esa_contrasena_el_usuario_entra_y_debe_cambiarla(self):
        self.crear_con_clave_conocida()
        self.assertTrue(
            Client().login(
                correo_institucional='diana.directora@unipamplona.edu.co',
                password=self.CLAVE,
            )
        )
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertTrue(usuario.requiere_cambio_contrasena)

    def test_el_envio_queda_en_auditoria(self):
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        registro = self.ultimo_envio()
        self.assertEqual(registro.resultado, 'Éxito')
        self.assertEqual(registro.tabla_afectada, 'usuario')
        self.assertEqual(registro.id_registro_afectado, usuario.pk)

    def test_la_contrasena_no_queda_en_la_auditoria(self):
        self.crear_con_clave_conocida()
        for detalle in Auditoria.objects.values_list('detalle', flat=True):
            self.assertNotIn(self.CLAVE, detalle or '')

    def test_si_el_correo_falla_el_usuario_queda_creado_y_se_avisa(self):
        # MSG-10-08 y EX-03 del BRD: la cuenta se crea y el fallo se registra.
        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=OSError('sin servicio de correo'),
        ):
            respuesta = self.crear(follow=True)
        self.assertTrue(Usuario.objects.filter(cedula='1020304050').exists())
        self.assertEqual(self.ultimo_envio().resultado, 'Fallo')
        avisos = list(respuesta.context['messages'])
        self.assertEqual(len(avisos), 1)
        # Aviso, no éxito: el ADMO tiene que enterarse de que hay que reenviarlo.
        self.assertEqual(avisos[0].level_tag, 'warning')
        self.assertIn('no se pudo enviar el correo', str(avisos[0]))
        # Y se ve de verdad en la pantalla, no solo en el contexto: la lista
        # incluye `_mensajes.html`, que lo pinta como `alert-warning`.
        self.assertContains(respuesta, 'no se pudo enviar el correo')
        self.assertContains(respuesta, 'alert-warning')

    def test_si_el_correo_sale_se_ve_el_mensaje_de_exito(self):
        respuesta = self.crear(follow=True)
        avisos = list(respuesta.context['messages'])
        self.assertEqual(len(avisos), 1)
        self.assertEqual(avisos[0].level_tag, 'success')
        self.assertIn('Se creó a Diana Directora', str(avisos[0]))
        self.assertContains(respuesta, 'alert-success')

    def test_editar_un_usuario_no_manda_ningun_correo(self):
        self.crear()
        mail.outbox.clear()
        self.client.post(
            reverse('usuarios:usuario_editar', args=[self.administrador.pk]),
            {
                'nombre': 'Ana Corregida',
                'cedula': self.administrador.cedula,
                'correo_institucional': self.administrador.correo_institucional,
                'rol': self.rol_administrador.pk,
                'carrera': '',
            },
        )
        self.assertEqual(len(mail.outbox), 0)


class DobleEnvioAlCrearUsuario(TransactionTestCase):
    """C9 · caja gris: dos POST simultáneos dejan una cuenta y un solo correo.

    El plan de cambios lo pide para toda acción que guarde algo. Sin el arreglo,
    los dos hilos pasan la validación de únicos y el segundo revienta con
    `IntegrityError` después de haber generado su propia contraseña.
    """

    serialized_rollback = True

    def setUp(self):
        self.rol_administrador = Rol.objects.get(nombre='Administrador')
        self.administrador = Usuario.objects.create_user(
            correo_institucional='admin@unipamplona.edu.co',
            password='ClaveDePrueba123',
            nombre='Ana Admin',
            cedula='1000000001',
            nombre_usuario='admin',
            rol=self.rol_administrador,
            requiere_cambio_contrasena=False,
        )
        mail.outbox.clear()

    def test_dos_envios_simultaneos_crean_un_solo_usuario(self):
        datos = {
            'nombre': 'Diana Directora',
            'cedula': '1020304050',
            'correo_institucional': 'diana.directora@unipamplona.edu.co',
            'rol': self.rol_administrador.pk,
            'carrera': '',
        }
        url = reverse('usuarios:usuario_nuevo')
        respuestas, fallos = [], []
        listos = threading.Barrier(2)

        def clave_lenta(_longitud):
            # El retraso deja a los dos hilos entre la validación y el INSERT,
            # que es donde se pelean: así la carrera es reproducible.
            time.sleep(0.2)
            return 'ClaveTemporalDePrueba'

        def enviar():
            cliente = Client()
            cliente.force_login(self.administrador)
            try:
                listos.wait(timeout=10)
                respuestas.append(cliente.post(url, datos))
            except Exception as error:  # el 500 que no debe pasar
                fallos.append(error)
            finally:
                connection.close()

        with patch(
            'apps.usuarios.forms.roles.get_random_string', side_effect=clave_lenta
        ):
            hilos = [threading.Thread(target=enviar) for _ in range(2)]
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join(timeout=30)

        self.assertEqual(fallos, [])
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            Auditoria.objects.filter(accion='Enviar credenciales').count(), 1
        )
        # Los dos intentos dejan huella: el que entró con Éxito y el rechazado
        # con Fallo, que es lo que pide la regla de auditoría del plan.
        self.assertEqual(
            Auditoria.objects.filter(accion='Crear usuario', resultado='Éxito').count(),
            1,
        )
        self.assertEqual(
            Auditoria.objects.filter(accion='Crear usuario', resultado='Fallo').count(),
            1,
        )
        codigos = sorted(respuesta.status_code for respuesta in respuestas)
        # Uno redirige al listado; el otro se queda en el formulario con el error.
        self.assertEqual(codigos, [200, 302])
        rechazada = next(
            respuesta for respuesta in respuestas if respuesta.status_code == 200
        )
        # Sin esto, el 200 podría ser un formulario mudo y la prueba seguiría verde.
        self.assertContains(rechazada, 'Otro envío se adelantó')


class EditarUsuarios(BaseRoles):
    """C6 · El ADMO edita los datos de un usuario y le cambia el rol."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.sistemas = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')
        self.civil = self.crear_carrera('Ingeniería Civil', 'IC-01')
        self.usuario = self.crear_usuario(
            'pedro.diaz@unipamplona.edu.co',
            nombre='Pedro Díaz',
            cedula='1055555555',
            rol=self.rol_estudiante,
        )

    def editar(self, usuario, **cambios):
        datos = {
            'nombre': usuario.nombre,
            'cedula': usuario.cedula,
            'correo_institucional': usuario.correo_institucional,
            'rol': usuario.rol_id,
            'carrera': '',
        }
        datos.update(cambios)
        return self.client.post(
            reverse('usuarios:usuario_editar', args=[usuario.pk]), datos
        )

    def hacer_director(self, usuario, carrera):
        self.editar(usuario, rol=self.rol_director.pk, carrera=carrera.pk)
        usuario.refresh_from_db()
        return usuario

    def test_cambia_los_datos(self):
        respuesta = self.editar(self.usuario, nombre='Pedro Díaz Mora')
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre, 'Pedro Díaz Mora')

    def test_cambia_el_rol(self):
        self.editar(self.usuario, rol=self.rol_administrador.pk)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.rol, self.rol_administrador)

    def test_al_volverlo_director_se_le_crea_el_perfil_y_la_asignacion(self):
        self.hacer_director(self.usuario, self.sistemas)
        self.assertTrue(Director.objects.filter(usuario=self.usuario).exists())
        asignacion = DirectorCarrera.objects.get(director__usuario=self.usuario)
        self.assertEqual(asignacion.carrera, self.sistemas)
        self.assertTrue(asignacion.activo)

    def test_cambiarle_la_carrera_cierra_la_anterior_y_abre_la_nueva(self):
        self.hacer_director(self.usuario, self.sistemas)
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.civil.pk)

        anterior = DirectorCarrera.objects.get(
            director__usuario=self.usuario, carrera=self.sistemas
        )
        self.assertFalse(anterior.activo)
        self.assertIsNotNone(anterior.fecha_fin)

        nueva = DirectorCarrera.objects.get(
            director__usuario=self.usuario, carrera=self.civil
        )
        self.assertTrue(nueva.activo)
        # La carrera anterior queda libre para otro Director.
        self.assertFalse(
            DirectorCarrera.objects.filter(carrera=self.sistemas, activo=True).exists()
        )

    def test_quitarle_el_rol_de_director_cierra_su_asignacion_sin_borrarla(self):
        self.hacer_director(self.usuario, self.sistemas)
        self.editar(self.usuario, rol=self.rol_estudiante.pk, carrera='')

        asignacion = DirectorCarrera.objects.get(director__usuario=self.usuario)
        self.assertFalse(asignacion.activo)
        self.assertIsNotNone(asignacion.fecha_fin)
        # El historial se conserva (regla §17): la fila sigue ahí.
        self.assertEqual(DirectorCarrera.objects.count(), 1)

    def test_no_puede_cambiarse_el_rol_a_si_mismo(self):
        respuesta = self.editar(self.administrador, rol=self.rol_estudiante.pk)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.rol, self.rol_administrador)

    def test_si_puede_cambiarse_sus_propios_datos(self):
        self.editar(self.administrador, nombre='Ana Admin Mora')
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.nombre, 'Ana Admin Mora')

    def test_con_usuario_editar_pero_sin_usuario_inactivar_no_se_cambia_el_estado(self):
        editor = self.crear_usuario(
            'editor@unipamplona.edu.co',
            nombre='Solo Edita',
            cedula='4040404040',
            rol=self.crear_rol_con('Edición', 'usuario.ver', 'usuario.editar'),
        )
        self.client.force_login(editor)
        self.client.post(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk]),
            {
                'nombre': self.usuario.nombre,
                'cedula': self.usuario.cedula,
                'correo_institucional': self.usuario.correo_institucional,
                'rol': self.usuario.rol_id,
                'carrera': '',
                'estado': Estado.INACTIVO,
            },
        )
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.estado, Estado.ACTIVO)

    def test_sin_el_permiso_no_se_puede_editar(self):
        self.client.force_login(self.usuario)
        respuesta = self.editar(self.usuario, nombre='Me Edito Solo')
        self.assertEqual(respuesta.status_code, 403)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre, 'Pedro Díaz')


class EliminarUsuarios(BaseRoles):
    """C8 · Se elimina un usuario que no tenga nada registrado; los demás se inactivan.

    La profesora fijó que ningún estudiante se borra, solo se deshabilita. Eso
    lo garantiza la base: todo lo que apunta a `usuario` es ON DELETE RESTRICT.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.suelto = self.crear_usuario(
            'creado.por.error@unipamplona.edu.co',
            nombre='Creado Por Error',
            cedula='1066666666',
            rol=self.rol_estudiante,
        )
        self.estudiante = self.crear_usuario(
            'sofia.lara@unipamplona.edu.co',
            nombre='Sofía Lara',
            cedula='1077777777',
            rol=self.rol_estudiante,
        )
        self.inscripcion = self.inscribir_en_carrera(
            self.estudiante, 'Ingeniería de Sistemas', 'IS-01'
        )

    def eliminar(self, usuario):
        return self.client.post(reverse('usuarios:usuario_eliminar', args=[usuario.pk]))

    def test_un_usuario_sin_nada_registrado_si_se_elimina(self):
        respuesta = self.eliminar(self.suelto)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.assertFalse(Usuario.objects.filter(cedula='1066666666').exists())

    def test_un_estudiante_no_se_elimina_aunque_no_tenga_tramites(self):
        # Lo protege su propia fila en `estudiante`: la regla de la profesora.
        respuesta = self.eliminar(self.estudiante)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.assertTrue(Usuario.objects.filter(pk=self.estudiante.pk).exists())

    def test_un_estudiante_con_tramites_tampoco_se_elimina(self):
        ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.PENDIENTE,
        )
        self.eliminar(self.estudiante)
        self.assertTrue(Usuario.objects.filter(pk=self.estudiante.pk).exists())
        self.assertTrue(ProcesoTrabajoSocial.objects.exists())

    def test_cuando_no_se_puede_eliminar_se_ofrece_inactivar(self):
        respuesta = self.client.post(
            reverse('usuarios:usuario_eliminar', args=[self.estudiante.pk]), follow=True
        )
        self.assertContains(respuesta, 'no se puede')
        self.assertContains(respuesta, 'inactivarlo')

    def test_un_director_no_se_elimina(self):
        director = Director.objects.create(usuario=self.suelto)
        DirectorCarrera.objects.create(
            director=director,
            carrera=self.crear_carrera('Ingeniería Civil', 'IC-01'),
            fecha_inicio=timezone.localdate(),
        )
        self.eliminar(self.suelto)
        self.assertTrue(Usuario.objects.filter(pk=self.suelto.pk).exists())

    def test_no_puede_eliminar_su_propia_cuenta(self):
        respuesta = self.eliminar(self.administrador)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.assertTrue(Usuario.objects.filter(pk=self.administrador.pk).exists())

    def test_eliminar_solo_acepta_post(self):
        respuesta = self.client.get(
            reverse('usuarios:usuario_eliminar', args=[self.suelto.pk])
        )
        self.assertEqual(respuesta.status_code, 405)
        self.assertTrue(Usuario.objects.filter(pk=self.suelto.pk).exists())

    def test_sin_el_permiso_no_se_puede_eliminar(self):
        self.client.force_login(self.estudiante)
        respuesta = self.eliminar(self.suelto)
        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(Usuario.objects.filter(pk=self.suelto.pk).exists())


class AuditoriaDeLosCambios(BaseRoles):
    """C10 · Todo cambio de usuarios, roles y permisos queda en `auditoria`."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.usuario = self.crear_usuario(
            'ruth.vega@unipamplona.edu.co',
            nombre='Ruth Vega',
            cedula='1088888888',
            rol=self.rol_estudiante,
        )

    def ultima(self, accion=None):
        # Crear un usuario deja dos registros desde SIS-69 (B3): «Crear usuario»
        # y «Enviar credenciales». Quien mire uno concreto lo pide por su acción.
        registros = Auditoria.objects.all()
        if accion is not None:
            registros = registros.filter(accion=accion)
        return registros.latest('id_auditoria')

    def test_crear_un_usuario_queda_registrado(self):
        self.client.post(
            reverse('usuarios:usuario_nuevo'),
            {
                'nombre': 'Hugo Mena',
                'cedula': '1099999999',
                'correo_institucional': 'hugo.mena@unipamplona.edu.co',
                'rol': self.rol_estudiante.pk,
                'carrera': '',
            },
        )
        creado = Usuario.objects.get(cedula='1099999999')
        registro = self.ultima('Crear usuario')
        self.assertEqual(registro.accion, 'Crear usuario')
        self.assertEqual(registro.tabla_afectada, 'usuario')
        self.assertEqual(registro.id_registro_afectado, creado.pk)
        self.assertEqual(registro.resultado, 'Éxito')
        self.assertIn('Hugo Mena', registro.detalle)

    def test_la_auditoria_guarda_quien_lo_hizo_y_cuando(self):
        antes = timezone.now()
        self.client.post(reverse('usuarios:usuario_estado', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.usuario, self.administrador)
        self.assertGreaterEqual(registro.fecha_hora, antes)

    def test_editar_guarda_el_valor_anterior_y_el_nuevo(self):
        self.client.post(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk]),
            {
                'nombre': 'Ruth Vega Ariza',
                'cedula': self.usuario.cedula,
                'correo_institucional': self.usuario.correo_institucional,
                'rol': self.rol_administrador.pk,
                'carrera': '',
            },
        )
        detalle = self.ultima().detalle
        self.assertIn('nombre: Ruth Vega → Ruth Vega Ariza', detalle)
        self.assertIn('rol: Estudiante → Administrador', detalle)

    def test_cambiar_el_estado_queda_registrado_con_el_antes_y_el_despues(self):
        self.client.post(reverse('usuarios:usuario_estado', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Cambiar estado de usuario')
        self.assertIn('estado: Activo → Inactivo', registro.detalle)

    def test_eliminar_queda_registrado_con_los_datos_del_usuario(self):
        self.client.post(reverse('usuarios:usuario_eliminar', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Eliminar usuario')
        self.assertEqual(registro.resultado, 'Éxito')
        self.assertIn('ruth.vega@unipamplona.edu.co', registro.detalle)

    def test_un_borrado_que_falla_tambien_queda_registrado(self):
        self.inscribir_en_carrera(self.usuario, 'Ingeniería de Sistemas', 'IS-01')
        self.client.post(reverse('usuarios:usuario_eliminar', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Eliminar usuario')
        self.assertEqual(registro.resultado, 'Fallo')

    def test_la_auditoria_no_impide_eliminar_al_usuario_auditado(self):
        # `auditoria.id_usuario` es quien HIZO la acción; a quién se le hizo va
        # en `id_registro_afectado`, que no es clave foránea.
        self.client.post(reverse('usuarios:usuario_estado', args=[self.usuario.pk]))
        self.assertTrue(
            Auditoria.objects.filter(id_registro_afectado=self.usuario.pk).exists()
        )
        self.client.post(reverse('usuarios:usuario_eliminar', args=[self.usuario.pk]))
        self.assertFalse(Usuario.objects.filter(cedula='1088888888').exists())
        self.assertTrue(
            Auditoria.objects.filter(id_registro_afectado=self.usuario.pk).exists()
        )

    def test_crear_un_rol_con_permisos_queda_registrado(self):
        self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Auditor',
                'descripcion': 'Solo consulta.',
                'permisos': [Permiso.objects.get(nombre='usuario.ver').pk],
            },
        )
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Crear rol')
        self.assertEqual(registro.tabla_afectada, 'rol')
        self.assertIn('permisos +[usuario.ver]', registro.detalle)

    def test_quitarle_un_permiso_a_un_rol_queda_registrado(self):
        rol = self.crear_rol_con('Auditor', 'usuario.ver', 'rol.ver')
        self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {
                'nombre': rol.nombre,
                'descripcion': '',
                'permisos': [Permiso.objects.get(nombre='rol.ver').pk],
            },
        )
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Editar rol')
        self.assertIn('permisos -[usuario.ver]', registro.detalle)

    def test_cambiar_el_estado_de_un_rol_queda_registrado(self):
        rol = self.crear_rol_con('Auditor', 'usuario.ver')
        self.client.post(reverse('usuarios:rol_estado', args=[rol.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Cambiar estado de rol')
        self.assertIn('estado: Activo → Inactivo', registro.detalle)


class ColumnaCarreraEnLaLista(BaseRoles):
    """C9 · La lista de usuarios muestra Nombre, Cédula, Correo, Carrera, Rol y Estado."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)

    def pantalla(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_la_tabla_tiene_las_seis_columnas(self):
        respuesta = self.pantalla()
        for columna in ('Nombre', 'Cédula', 'correo', 'Carrera', 'Rol', 'Estado'):
            self.assertContains(respuesta, columna)

    def test_muestra_las_carreras_del_estudiante(self):
        estudiante = self.crear_usuario(
            'luis.mora@unipamplona.edu.co',
            nombre='Luis Mora',
            cedula='1033333333',
            rol=self.rol_estudiante,
        )
        inscripcion = self.inscribir_en_carrera(
            estudiante, 'Ingeniería de Sistemas', 'IS-01'
        )
        EstudianteCarrera.objects.create(
            estudiante=inscripcion.estudiante,
            carrera=self.crear_carrera('Ingeniería Civil', 'IC-01'),
            estado=EstadoInscripcion.ACTIVO,
        )
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'Ingeniería de Sistemas')
        self.assertContains(respuesta, 'Ingeniería Civil')

    def test_muestra_la_carrera_vigente_del_director(self):
        usuario = self.crear_usuario(
            'dora.prado@unipamplona.edu.co',
            nombre='Dora Prado',
            cedula='1044444444',
            rol=Rol.objects.get(nombre='Director'),
        )
        director = Director.objects.create(usuario=usuario)
        DirectorCarrera.objects.create(
            director=director,
            carrera=self.crear_carrera('Ingeniería de Sistemas', 'IS-01'),
            fecha_inicio=timezone.localdate(),
            activo=True,
        )
        DirectorCarrera.objects.create(
            director=director,
            carrera=self.crear_carrera('Ingeniería Civil', 'IC-01'),
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate(),
            activo=False,
        )
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'Ingeniería de Sistemas')
        self.assertNotContains(respuesta, 'Ingeniería Civil')

    def test_si_no_tiene_carrera_la_celda_queda_vacia(self):
        respuesta = self.pantalla()
        self.assertEqual(respuesta.context['usuarios'][0].carreras, [])


class ElRolAdministradorNoSeQuedaSinSalida(BaseRoles):
    """Lo encontró el revisor: vaciarle los permisos al rol base dejaba el
    sistema sin ninguna pantalla y sin forma de volver atrás."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.minimos = ['rol.ver', 'rol.editar', 'rol.asignar_permisos']

    def editar_administrador(self, permisos):
        return self.client.post(
            reverse('usuarios:rol_editar', args=[self.rol_administrador.pk]),
            {
                'nombre': self.rol_administrador.nombre,
                'descripcion': self.rol_administrador.descripcion,
                'permisos': list(
                    Permiso.objects.filter(nombre__in=permisos).values_list('pk', flat=True)
                ),
            },
        )

    def permisos_del_administrador(self):
        return set(
            Permiso.objects.filter(asignaciones__rol=self.rol_administrador).values_list(
                'nombre', flat=True
            )
        )

    def test_no_se_le_pueden_quitar_todos_los_permisos(self):
        antes = self.permisos_del_administrador()
        respuesta = self.editar_administrador([])
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.permisos_del_administrador(), antes)

    def test_el_mensaje_dice_cuales_no_se_pueden_quitar(self):
        respuesta = self.editar_administrador([])
        errores = respuesta.context['formulario'].errors['permisos']
        self.assertEqual(len(errores), 1)
        for permiso in self.minimos:
            self.assertIn(permiso, errores[0])

    def test_despues_del_intento_el_sistema_sigue_accesible(self):
        self.editar_administrador([])
        self.assertEqual(self.client.get(reverse('usuarios:roles')).status_code, 200)
        self.assertEqual(self.client.get(reverse('usuarios:usuarios')).status_code, 200)

    def test_no_se_le_puede_quitar_solo_uno_de_los_minimos(self):
        for quitado in self.minimos:
            quedan = [p for p in self.minimos if p != quitado]
            respuesta = self.editar_administrador(quedan)
            self.assertEqual(respuesta.status_code, 200, f'dejó quitar {quitado}')
            self.assertIn(quitado, self.permisos_del_administrador())

    def test_los_demas_permisos_si_se_le_pueden_quitar(self):
        respuesta = self.editar_administrador(self.minimos)
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        self.assertEqual(self.permisos_del_administrador(), set(self.minimos))

    def test_con_los_minimos_todavia_se_puede_deshacer_el_cambio(self):
        # Esto es lo que hace que el mínimo sea el correcto: con esos tres se
        # vuelve a la pantalla y se reponen los demás.
        self.editar_administrador(self.minimos)
        self.assertEqual(self.client.get(reverse('usuarios:roles')).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse('usuarios:rol_editar', args=[self.rol_administrador.pk])
            ).status_code,
            200,
        )
        self.editar_administrador(self.minimos + ['usuario.ver', 'usuario.crear'])
        self.assertIn('usuario.crear', self.permisos_del_administrador())

    def test_a_los_otros_roles_base_si_se_les_puede_dejar_sin_permisos(self):
        # La guarda es solo del Administrador: Estudiante y Director no son
        # puerta de recuperación de nada.
        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[self.rol_estudiante.pk]),
            {'nombre': 'Estudiante', 'descripcion': '', 'permisos': []},
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))


class ArreglosDeLaRevision(BaseRoles):
    """Los cuatro CORREGIR del revisor, cada uno con su prueba."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.sistemas = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')
        self.civil = self.crear_carrera('Ingeniería Civil', 'IC-01')
        self.usuario = self.crear_usuario(
            'pedro.diaz@unipamplona.edu.co',
            nombre='Pedro Díaz',
            cedula='1055555555',
            rol=self.rol_estudiante,
        )

    def editar(self, usuario, **cambios):
        datos = {
            'nombre': usuario.nombre,
            'cedula': usuario.cedula,
            'correo_institucional': usuario.correo_institucional,
            'rol': usuario.rol_id,
            'carrera': '',
        }
        datos.update(cambios)
        return self.client.post(
            reverse('usuarios:usuario_editar', args=[usuario.pk]), datos
        )

    def ultima(self, accion=None):
        # Crear un usuario deja dos registros desde SIS-69 (B3): «Crear usuario»
        # y «Enviar credenciales». Quien mire uno concreto lo pide por su acción.
        registros = Auditoria.objects.all()
        if accion is not None:
            registros = registros.filter(accion=accion)
        return registros.latest('id_auditoria')

    # --- C-1 · la auditoría guardaba "—" como carrera anterior ---

    def test_al_crear_un_director_la_auditoria_guarda_su_carrera(self):
        self.client.post(
            reverse('usuarios:usuario_nuevo'),
            {
                'nombre': 'Dora Prado',
                'cedula': '1044444444',
                'correo_institucional': 'dora.prado@unipamplona.edu.co',
                'rol': self.rol_director.pk,
                'carrera': self.sistemas.pk,
            },
        )
        detalle = self.ultima('Crear usuario').detalle
        self.assertIn('carrera: — → Ingeniería de Sistemas', detalle)

    def test_cambiarle_la_carrera_guarda_la_anterior_y_la_nueva(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.usuario.refresh_from_db()
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.civil.pk)
        self.assertIn(
            'carrera: Ingeniería de Sistemas → Ingeniería Civil', self.ultima().detalle
        )

    def test_quitarle_el_rol_de_director_deja_el_cierre_en_la_auditoria(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.usuario.refresh_from_db()
        self.editar(self.usuario, rol=self.rol_estudiante.pk, carrera='')
        detalle = self.ultima().detalle
        self.assertIn('rol: Director → Estudiante', detalle)
        self.assertIn('carrera: Ingeniería de Sistemas → — (asignación cerrada)', detalle)

    def test_si_la_carrera_no_cambia_no_se_inventa_una_linea(self):
        self.editar(self.usuario, nombre='Pedro Díaz Mora')
        self.assertNotIn('carrera', self.ultima().detalle)

    # --- C-2 · un Director con su carrera inactivada quedaba congelado ---

    def test_un_director_con_la_carrera_inactivada_se_puede_seguir_editando(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.usuario.refresh_from_db()
        # Lo hará SISTRA-11, que administra el catálogo de carreras.
        self.sistemas.estado = Estado.INACTIVO
        self.sistemas.save(update_fields=['estado'])

        respuesta = self.editar(
            self.usuario,
            nombre='Pedro Díaz Mora',
            rol=self.rol_director.pk,
            carrera=self.sistemas.pk,
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre, 'Pedro Díaz Mora')

    def test_la_pantalla_muestra_la_carrera_inactivada_del_director(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.sistemas.estado = Estado.INACTIVO
        self.sistemas.save(update_fields=['estado'])
        respuesta = self.client.get(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk])
        )
        opciones = respuesta.context['formulario'].fields['carrera'].queryset
        self.assertIn(self.sistemas, opciones)

    # --- C-3 · el nombre de usuario quedaba contradiciendo al correo ---

    def test_al_cambiar_el_correo_se_vuelve_a_derivar_el_nombre_de_usuario(self):
        self.editar(self.usuario, correo_institucional='pedro.gomez@unipamplona.edu.co')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.correo_institucional, 'pedro.gomez@unipamplona.edu.co')
        self.assertEqual(self.usuario.nombre_usuario, 'pedro.gomez')

    def test_editar_sin_tocar_el_correo_no_le_pone_numero_al_nombre_de_usuario(self):
        self.editar(self.usuario, nombre='Pedro Díaz Mora')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre_usuario, 'pedro.diaz')

    def test_si_el_nombre_derivado_ya_esta_tomado_se_le_agrega_un_numero(self):
        self.crear_usuario(
            'pedro.gomez@otrodominio.edu.co', nombre='Pedro Homónimo', cedula='8888888888'
        )
        self.editar(self.usuario, correo_institucional='pedro.gomez@unipamplona.edu.co')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre_usuario, 'pedro.gomez-2')

    # --- O-6 · el botón de eliminar se ofrecía a quien nunca se puede borrar ---

    def test_no_se_ofrece_eliminar_a_un_estudiante_con_perfil(self):
        self.inscribir_en_carrera(self.usuario, 'Ingeniería Industrial', 'II-01')
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertNotContains(
            respuesta, reverse('usuarios:usuario_eliminar', args=[self.usuario.pk])
        )

    def test_si_se_ofrece_eliminar_a_una_cuenta_sin_perfil(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertContains(
            respuesta, reverse('usuarios:usuario_eliminar', args=[self.usuario.pk])
        )

    # --- O-5 · que nadie rompa el prefetch sin darse cuenta ---

    def test_la_lista_no_hace_consultas_por_fila(self):
        self.poblar(3, desde=20)
        with CaptureQueriesContext(connection) as con_pocos:
            self.client.get(reverse('usuarios:usuarios'))
        self.poblar(9, desde=40)
        with CaptureQueriesContext(connection) as con_muchos:
            self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(
            len(con_pocos.captured_queries),
            len(con_muchos.captured_queries),
            'la lista hace consultas por fila: se rompió el prefetch',
        )

    def poblar(self, cuantos, desde):
        for i in range(cuantos):
            usuario = self.crear_usuario(
                f'persona{desde + i}@unipamplona.edu.co',
                nombre=f'Persona {desde + i}',
                cedula=f'20{desde + i:08d}',
                rol=self.rol_estudiante,
            )
            self.inscribir_en_carrera(
                usuario, f'Carrera {desde + i}', f'C-{desde + i:03d}'
            )


class DominioInstitucionalDelCorreo(BaseRoles):
    """SIS-42 · crear y editar usuarios exigen el dominio institucional.

    Con ese correo se entra al sistema (RG-14) y el login de SISTRA-13 solo
    acepta `@unipamplona.edu.co`, así que un dominio ajeno deja la cuenta
    creada y sin poder ingresar.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.usuario = self.crear_usuario(
            'pedro.diaz@unipamplona.edu.co',
            nombre='Pedro Díaz',
            cedula='1055555555',
            rol=self.rol_estudiante,
        )

    def datos(self, **cambios):
        datos = {
            'nombre': 'Laura Peña',
            'cedula': '1020304050',
            'correo_institucional': 'laura.pena@unipamplona.edu.co',
            'rol': self.rol_estudiante.pk,
            'carrera': '',
        }
        datos.update(cambios)
        return datos

    def crear(self, **cambios):
        return self.client.post(reverse('usuarios:usuario_nuevo'), self.datos(**cambios))

    def editar(self, **cambios):
        datos = self.datos(
            nombre=self.usuario.nombre,
            cedula=self.usuario.cedula,
            correo_institucional=self.usuario.correo_institucional,
            rol=self.usuario.rol_id,
        )
        datos.update(cambios)
        return self.client.post(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk]), datos
        )

    def test_crear_con_otro_dominio_no_guarda(self):
        respuesta = self.crear(correo_institucional='laura.pena@ejemplo.edu.co')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'unipamplona.edu.co')
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_crear_con_un_dominio_que_solo_se_parece_no_guarda(self):
        respuesta = self.crear(correo_institucional='laura@mail.unipamplona.edu.co.co')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_editar_con_otro_dominio_no_guarda(self):
        respuesta = self.editar(correo_institucional='pedro.diaz@ejemplo.edu.co')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'unipamplona.edu.co')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.correo_institucional, 'pedro.diaz@unipamplona.edu.co')

    def test_crear_acepta_el_institucional_con_mayusculas_y_espacios(self):
        respuesta = self.crear(correo_institucional='  LAURA.PENA@UNIPAMPLONA.EDU.CO  ')
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.correo_institucional, 'laura.pena@unipamplona.edu.co')
        # El nombre de usuario sale del correo ya normalizado.
        self.assertEqual(usuario.nombre_usuario, 'laura.pena')

    def test_editar_acepta_el_institucional_con_mayusculas_y_espacios(self):
        respuesta = self.editar(
            correo_institucional='  PEDRO.DIAZ.MORA@UNIPAMPLONA.EDU.CO  '
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.usuario.refresh_from_db()
        self.assertEqual(
            self.usuario.correo_institucional, 'pedro.diaz.mora@unipamplona.edu.co'
        )

    def test_el_mismo_correo_en_mayusculas_no_crea_un_duplicado(self):
        respuesta = self.crear(
            cedula='1077777777', correo_institucional='PEDRO.DIAZ@UNIPAMPLONA.EDU.CO'
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            Usuario.objects.filter(
                correo_institucional__iexact='pedro.diaz@unipamplona.edu.co'
            ).count(),
            1,
        )
