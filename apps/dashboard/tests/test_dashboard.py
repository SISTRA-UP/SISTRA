import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.dashboard.views.dashboard import MSG_14_02
from apps.parametrizacion.models import (
    Carrera,
    EstadoPeriodo,
    Facultad,
    Parametro,
    PeriodoAcademico,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO
from apps.propuestas.models import EstadoTramite, Propuesta
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
        self.assertContains(respuesta, 'Mi propuesta')
        self.assertContains(respuesta, 'Mi informe')
        self.assertContains(respuesta, 'Cargue en UP')
        self.assertContains(respuesta, 'Avance general del proceso')
        self.assertContains(respuesta, 'Ingeniería de Sistemas')

    def test_estudiante_no_puede_abrir_panel_administrador(self):
        self.client.force_login(self.estudiante_user)
        respuesta = self.client.get(reverse('dashboard:administrador'))
        self.assertEqual(respuesta.status_code, 403)


class DashboardIntegracionTests(TestCase):
    def setUp(self):
        self.rol_admin = Rol.objects.get(nombre='Administrador')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.rol_director = Rol.objects.get(nombre='Director')

        self.facultad = Facultad.objects.create(nombre='Facultad de Salud')
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Enfermería',
            codigo='ENF-TEST',
        )
        hoy = timezone.localdate()
        self.periodo = PeriodoAcademico.objects.create(
            nombre='2026-2',
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin=hoy + timedelta(days=90),
            fecha_cierre_propuesta=hoy + timedelta(days=30),
            fecha_cierre_informe=hoy + timedelta(days=60),
            estado=EstadoPeriodo.VIGENTE,
        )

        self.admin = Usuario.objects.create_user(
            correo_institucional='admin.int@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_admin,
            nombre='Admin Integracion',
            cedula='910000001',
            nombre_usuario='admin_int',
            requiere_cambio_contrasena=False,
        )
        self.director_user = Usuario.objects.create_user(
            correo_institucional='dir.int@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_director,
            nombre='Director Integracion',
            cedula='910000002',
            nombre_usuario='dir_int',
            requiere_cambio_contrasena=False,
        )
        self.director = Director.objects.create(usuario=self.director_user)
        DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=hoy,
            activo=True,
        )

        self.estudiante_user = Usuario.objects.create_user(
            correo_institucional='est.int@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_estudiante,
            nombre='Estudiante Integracion',
            cedula='910000003',
            nombre_usuario='est_int',
            requiere_cambio_contrasena=False,
        )
        self.estudiante = Estudiante.objects.create(usuario=self.estudiante_user)
        self.inscripcion = EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            estado=EstadoInscripcion.ACTIVO,
        )

    def _crear_propuesta_en_revision(self, dias_atras, codigo='PROP-INT-001'):
        campo_estado = ProcesoTrabajoSocial._meta.get_field('estado')
        estado_inicial = (
            campo_estado.default
            if campo_estado.default is not models.NOT_PROVIDED
            else campo_estado.choices[0][0]
        )
        proceso = ProcesoTrabajoSocial.objects.create(
         estudiante_carrera=self.inscripcion,
         fecha_inicio=timezone.now() - timedelta(days=dias_atras),
         estado=estado_inicial,
        )
        return Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=self.periodo,
            codigo=codigo,
            titulo='Propuesta de integración',
            estado=EstadoTramite.EN_REVISION,
            fecha_envio=timezone.now() - timedelta(days=dias_atras, hours=1),
        )

    def test_el_inicio_de_cada_rol_lleva_al_dashboard(self):
        casos = [
            (self.estudiante_user, 'usuarios:inicio_estudiante', 'Mi Trabajo Social'),
            (self.director_user, 'usuarios:inicio_director', 'Mis estudiantes'),
            (self.admin, 'usuarios:inicio_administrador', 'Administración'),
        ]
        for usuario, ruta_inicio, titulo_esperado in casos:
            with self.subTest(rol=usuario.rol.nombre):
                self.client.force_login(usuario)
                respuesta = self.client.get(reverse(ruta_inicio), follow=True)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, titulo_esperado)

    def test_ningun_acceso_queda_vacio_ni_roto(self):
        for usuario in (self.estudiante_user, self.director_user, self.admin):
            with self.subTest(rol=usuario.rol.nombre):
                self.client.force_login(usuario)
                respuesta = self.client.get(reverse('dashboard:inicio'), follow=True)
                self.assertEqual(respuesta.status_code, 200)
                html = respuesta.content.decode('utf-8')
                self.assertNotIn('href="#"', html)
                self.assertNotIn("href='#'", html)

                enlaces = re.findall(r'<a\b[^>]*\bhref=["\']([^"\']+)["\']', html)
                for enlace in enlaces:
                    if enlace.startswith('/'):
                        resp_enlace = self.client.get(enlace)
                        self.assertNotIn(
                            resp_enlace.status_code,
                            (403, 404, 500),
                            f'Enlace inválido para {usuario.rol.nombre}: {enlace} ({resp_enlace.status_code})',
                        )

    def test_el_director_tiene_acceso_a_verificar_informes(self):
        self.client.force_login(self.director_user)
        respuesta = self.client.get(reverse('dashboard:director'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Verificar cargues de informes')
        self.assertContains(respuesta, reverse('cargue_up:verificacion_informe_lista'))

    def test_semaforo_igual_al_de_la_bandeja_con_valores_iniciales(self):
        Parametro.objects.filter(
            clave__in=['semaforo.verde_hasta_dias', 'semaforo.amarillo_hasta_dias']
        ).delete()
        self._crear_propuesta_en_revision(dias_atras=10, codigo='PROP-SEM-10')

        self.client.force_login(self.director_user)
        respuesta = self.client.get(reverse('dashboard:director'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, '10 d · Por vencer')

    def test_semaforo_usa_los_umbrales_de_parametrizacion(self):
        Parametro.objects.update_or_create(
            clave='semaforo.verde_hasta_dias',
            defaults={'valor': '2', 'usuario_actualizacion': self.admin},
        )
        Parametro.objects.update_or_create(
            clave='semaforo.amarillo_hasta_dias',
            defaults={'valor': '4', 'usuario_actualizacion': self.admin},
        )
        self._crear_propuesta_en_revision(dias_atras=3, codigo='PROP-SEM-03')

        self.client.force_login(self.director_user)
        respuesta = self.client.get(reverse('dashboard:director'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, '3 d · Por vencer')

    def test_la_auditoria_usa_el_vocabulario_estandar(self):
        self.client.force_login(self.admin)
        self.client.get(reverse('dashboard:administrador'))
        registro = Auditoria.objects.filter(
            usuario=self.admin, accion='CONSULTA_DASHBOARD'
        ).latest('id_auditoria')
        self.assertEqual(registro.resultado, RESULTADO_EXITO)

    def test_falla_al_cargar_muestra_msg_14_02_con_reintentar(self):
        self.client.force_login(self.estudiante_user)
        with patch(
            'apps.dashboard.views.dashboard.construir_contexto_estudiante',
            side_effect=RuntimeError('Detalle tecnico interno'),
        ):
            respuesta = self.client.get(reverse('dashboard:estudiante'))
        self.assertEqual(respuesta.status_code, 500)
        self.assertContains(respuesta, MSG_14_02, status_code=500)
        self.assertContains(respuesta, 'Reintentar', status_code=500)
        self.assertNotContains(respuesta, 'Detalle tecnico interno', status_code=500)

    def test_tiene_cerrar_sesion_y_mensaje_sin_pendientes(self):
        self.client.force_login(self.estudiante_user)
        respuesta = self.client.get(reverse('dashboard:estudiante'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, f'action="{reverse("usuarios:logout")}"')
        self.assertContains(respuesta, 'Cerrar sesión')
        self.assertContains(respuesta, 'No tienes acciones pendientes.')

    def test_el_estudiante_puede_cambiar_de_carrera(self):
        segunda_carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Bacteriología',
            codigo='BAC-TEST',
        )
        EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=segunda_carrera,
            estado=EstadoInscripcion.ACTIVO,
        )

        self.client.force_login(self.estudiante_user)
        respuesta = self.client.get(
            reverse('dashboard:estudiante'),
            {'carrera': segunda_carrera.pk},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.context['inscripcion_actual'].carrera,
            segunda_carrera,
        )
