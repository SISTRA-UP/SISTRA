"""SISTRA-03 · Cargue en la Plataforma UP: pruebas automatizadas.

Verifica los criterios de aceptación y seguridad del requerimiento BR-03 (SISTRA-03):
- Control de acceso estricto: solo el Estudiante autenticado accede (Director/ADMO reciben 403).
- Sin sesión redirige al login incluso con DEBUG=True.
- Aislamiento por estudiante: un estudiante no puede descargar ni abrir ir-up de propuesta ajena (404).
- CA-01: Estudiante con proyecto Aprobado ve controles habilitados.
- CA-02: Proyecto no Aprobado tiene controles deshabilitados.
- FA-02: Reactivación de controles y visualización de observaciones tras Rechazado en UP.
- Redirección 'Ir a la Plataforma UP' con y sin parámetro url_up configurado.
- Criterios 4 y 5: Comando de recordatorio semanal en plataforma (tabla Notificacion).
"""

from datetime import timedelta
from io import StringIO
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.parametrizacion.models import Carrera, Facultad, Parametro, PeriodoAcademico
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Rol

Usuario = get_user_model()


class CargueUpSecurityAndViewsTestCase(TestCase):
    """Pruebas de seguridad, vistas e integración para SISTRA-03."""

    def setUp(self):
        self.client = Client()

        # Roles
        self.rol_estudiante, _ = Rol.objects.get_or_create(nombre="Estudiante")
        self.rol_docente, _ = Rol.objects.get_or_create(nombre="Docente")
        self.rol_admin, _ = Rol.objects.get_or_create(nombre="Administrador")

        # Usuarios
        self.user_estudiante_1 = Usuario.objects.create_user(
            correo_institucional="estudiante1@unipamplona.edu.co",
            nombre_usuario="estudiante1",
            nombre="Juan Perez",
            cedula="1098765432",
            password="Password123!",
            rol=self.rol_estudiante,
        )
        self.user_estudiante_2 = Usuario.objects.create_user(
            correo_institucional="estudiante2@unipamplona.edu.co",
            nombre_usuario="estudiante2",
            nombre="Maria Gomez",
            cedula="1098765433",
            password="Password123!",
            rol=self.rol_estudiante,
        )
        self.user_docente = Usuario.objects.create_user(
            correo_institucional="docente@unipamplona.edu.co",
            nombre_usuario="docente",
            nombre="Prof. Carlos Ruiz",
            cedula="9876543210",
            password="Password123!",
            rol=self.rol_docente,
        )
        self.user_admo = Usuario.objects.create_user(
            correo_institucional="admo@unipamplona.edu.co",
            nombre_usuario="admo",
            nombre="Administrador General",
            cedula="9988776655",
            password="Password123!",
            rol=self.rol_admin,
        )

        # Estructura académica
        self.facultad = Facultad.objects.create(nombre="Facultad de Ingenierías y Arquitectura")
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre="Ingeniería de Sistemas",
            codigo="136",
        )
        self.periodo = PeriodoAcademico.objects.create(
            nombre="2026-2",
            fecha_inicio=timezone.localdate() - timedelta(days=30),
            fecha_fin=timezone.localdate() + timedelta(days=90),
            fecha_cierre_propuesta=timezone.localdate() + timedelta(days=40),
            fecha_cierre_informe=timezone.localdate() + timedelta(days=80),
            estado="Vigente",
        )

        # Personas y perfiles
        self.estudiante_1 = Estudiante.objects.create(usuario=self.user_estudiante_1)
        self.estudiante_2 = Estudiante.objects.create(usuario=self.user_estudiante_2)
        self.director = Director.objects.create(usuario=self.user_docente)

        self.director_carrera = DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=timezone.localdate() - timedelta(days=60),
            activo=True,
        )

        self.inscripcion_1 = EstudianteCarrera.objects.create(
            estudiante=self.estudiante_1,
            carrera=self.carrera,
            estado=EstadoInscripcion.ACTIVO,
        )
        self.inscripcion_2 = EstudianteCarrera.objects.create(
            estudiante=self.estudiante_2,
            carrera=self.carrera,
            estado=EstadoInscripcion.ACTIVO,
        )

        self.proceso_1 = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion_1,
            fecha_inicio=timezone.now() - timedelta(days=15),
            estado=EstadoAvance.EN_CURSO,
        )
        self.proceso_2 = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion_2,
            fecha_inicio=timezone.now() - timedelta(days=15),
            estado=EstadoAvance.EN_CURSO,
        )

        # Propuesta 1 (Aprobada hace 10 días)
        self.propuesta_1 = Propuesta.objects.create(
            proceso=self.proceso_1,
            periodo_academico=self.periodo,
            codigo="PROP-2026-001",
            titulo="Sistema de Gestión Comunitaria",
            estado=EstadoTramite.APROBADO,
            fecha_envio=timezone.now() - timedelta(days=12),
        )
        HistorialEstado.objects.create(
            propuesta=self.propuesta_1,
            usuario=self.user_docente,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.APROBADO,
            tipo_accion="Aprobación de propuesta",
            fecha_hora=timezone.now() - timedelta(days=10),
        )

        # Propuesta 2 (En revisión del Estudiante 2)
        self.propuesta_2 = Propuesta.objects.create(
            proceso=self.proceso_2,
            periodo_academico=self.periodo,
            codigo="PROP-2026-002",
            titulo="Alfabetización Digital",
            estado=EstadoTramite.EN_REVISION,
            fecha_envio=timezone.now() - timedelta(days=2),
        )

    # ==========================================================================
    # 1. PRUEBAS DE SEGURIDAD (AUTENTICACIÓN Y ROLES)
    # ==========================================================================

    @override_settings(DEBUG=True)
    def test_sin_sesion_redirige_a_login_incluso_en_debug(self):
        """Seguridad: Un usuario anónimo siempre es redirigido a login, incluso con DEBUG activo."""
        url_inicio = reverse("cargue_up:cargue_propuesta")
        url_descargar = reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk])
        url_ir_up = reverse("cargue_up:ir_a_up", args=[self.propuesta_1.pk])

        res_inicio = self.client.get(url_inicio)
        self.assertEqual(res_inicio.status_code, 302)
        self.assertIn("login", res_inicio.url)

        res_descargar = self.client.get(url_descargar)
        self.assertEqual(res_descargar.status_code, 302)
        self.assertIn("login", res_descargar.url)

        res_ir_up = self.client.get(url_ir_up)
        self.assertEqual(res_ir_up.status_code, 302)
        self.assertIn("login", res_ir_up.url)

    def test_director_o_admo_recibe_403(self):
        """Seguridad: Solo usuarios con perfil Estudiante pueden acceder a las vistas; Director y ADMO reciben 403."""
        # Intento como Docente/Director
        self.client.force_login(self.user_docente)

        res_inicio = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res_inicio.status_code, 403)

        res_descargar = self.client.get(reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk]))
        self.assertEqual(res_descargar.status_code, 403)

        res_ir_up = self.client.get(reverse("cargue_up:ir_a_up", args=[self.propuesta_1.pk]))
        self.assertEqual(res_ir_up.status_code, 403)

        # Intento como Administrador (staff)
        self.client.force_login(self.user_admo)
        res_admo = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res_admo.status_code, 403)

    def test_estudiante_no_puede_acceder_propuesta_ajena(self):
        """Seguridad: Un estudiante no puede descargar ni abrir ir-up de una propuesta que no es suya (404)."""
        self.client.force_login(self.user_estudiante_2)

        # Estudiante 2 intenta acceder a la propuesta 1 (pertenece a Estudiante 1)
        res_descargar = self.client.get(reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk]))
        self.assertEqual(res_descargar.status_code, 404)

        res_ir_up = self.client.get(reverse("cargue_up:ir_a_up", args=[self.propuesta_1.pk]))
        self.assertEqual(res_ir_up.status_code, 404)

    # ==========================================================================
    # 2. PRUEBAS FUNCIONALES DE VISTA INICIO Y ESTADOS (CA-01, CA-02, FA-02)
    # ==========================================================================

    def test_ca_01_estudiante_con_propuesta_aprobada(self):
        """CA-01: Estudiante con propuesta Aprobada ve controles habilitados para cargar en UP."""
        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:cargue_propuesta"))

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context["puede_cargar"])
        self.assertEqual(res.context["estado_actual"], EstadoTramite.APROBADO)
        self.assertContains(res, "Mi proyecto de horas sociales")
        self.assertContains(res, "Cargar el proyecto en la UP")

    def test_ca_02_propuesta_no_aprobada_deshabilita_acciones(self):
        """CA-02: Proyecto en estado no Aprobado tiene acciones deshabilitadas."""
        self.client.force_login(self.user_estudiante_2)
        res = self.client.get(reverse("cargue_up:cargue_propuesta"))

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context["puede_cargar"])
        self.assertContains(res, "disabled")

    def test_fa_02_botones_se_habilitan_otra_vez_tras_rechazado_en_up(self):
        """FA-02: Tras Rechazado en UP, la propuesta vuelve a Aprobado y se habilitan los botones mostrando la observación."""
        # Se registra un cargue previo que fue rechazado por el Director en UP
        CargueUp.objects.create(
            propuesta=self.propuesta_1,
            director=self.director,
            fecha_declaracion=timezone.now() - timedelta(days=3),
            estado_verificacion=EstadoVerificacion.RECHAZADO_EN_UP,
            fecha_verificacion=timezone.now() - timedelta(days=2),
            observacion="Falta adjuntar el oficio de aceptación firmado por la entidad receptora.",
        )

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:cargue_propuesta"))

        self.assertEqual(res.status_code, 200)
        # Los botones vuelven a estar habilitados
        self.assertTrue(res.context["puede_cargar"])
        # Se expone la observación del Director
        self.assertEqual(
            res.context["observacion_rechazo_up"],
            "Falta adjuntar el oficio de aceptación firmado por la entidad receptora.",
        )
        self.assertContains(res, "Falta adjuntar el oficio de aceptación firmado por la entidad receptora.")

    # ==========================================================================
    # 3. PRUEBAS DE IR A LA PLATAFORMA UP (CON Y SIN PARÁMETRO)
    # ==========================================================================

    def test_ir_up_con_url_up_configurada(self):
        """Con clave url_up configurada en Parametro, redirige a dicha URL y audita Éxito."""
        Parametro.objects.create(
            clave="url_up",
            valor="https://portal.unipamplona.edu.co/plataforma",
            descripcion="URL de la UP",
            usuario_actualizacion=self.user_admo,
        )

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:ir_a_up", args=[self.propuesta_1.pk]))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, "https://portal.unipamplona.edu.co/plataforma")

        auditoria = Auditoria.objects.filter(
            accion="Ir a la Plataforma UP",
            id_registro_afectado=self.propuesta_1.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.resultado, "Éxito")

    def test_ir_up_sin_url_up_configurada(self):
        """Sin clave url_up configurada, bloquea la acción, audita Bloqueado y redirige a inicio."""
        Parametro.objects.filter(clave="url_up").delete()

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:ir_a_up", args=[self.propuesta_1.pk]), follow=True)

        self.assertEqual(res.status_code, 200)

        auditoria = Auditoria.objects.filter(
            accion="Ir a la Plataforma UP",
            id_registro_afectado=self.propuesta_1.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.resultado, "Bloqueado")

    # ==========================================================================
    # 4. PRUEBAS DEL COMANDO DE RECORDATORIO SEMANAL (CRITERIOS 4 Y 5)
    # ==========================================================================

    def test_comando_recordatorio_semanal(self):
        """El comando genera notificaciones dentro de la plataforma cada 7 días para propuestas aprobadas."""
        out = StringIO()
        # La propuesta 1 fue aprobada hace 10 días (> 7 días), por lo que debe recibir recordatorio
        call_command("recordatorio_cargue_up", stdout=out)

        notificacion_1 = Notificacion.objects.filter(
            propuesta=self.propuesta_1,
            tipo="RECORDATORIO_CARGUE_UP",
        ).first()
        self.assertIsNotNone(notificacion_1)
        self.assertEqual(notificacion_1.usuario, self.user_estudiante_1)
        self.assertIn("Recordatorio semanal", notificacion_1.mensaje)

        # La propuesta 2 está en revisión, NO debe recibir recordatorio
        notificacion_2 = Notificacion.objects.filter(
            propuesta=self.propuesta_2,
            tipo="RECORDATORIO_CARGUE_UP",
        ).first()
        self.assertIsNone(notificacion_2)
