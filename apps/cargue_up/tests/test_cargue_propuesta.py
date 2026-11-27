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
from io import BytesIO, StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.cargue_up.forms.cargue_propuesta import MSG_03_03, MSG_03_04, MSG_03_05, MSG_03_06
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
        self.rol_director, _ = Rol.objects.get_or_create(nombre="Director")
        self.rol_admin, _ = Rol.objects.get_or_create(nombre="Administrador")

        # Usuarios (sin cambio de contraseña obligatorio, para no ser redirigidos por SISTRA-13)
        self.user_estudiante_1 = Usuario.objects.create_user(
            correo_institucional="estudiante1@unipamplona.edu.co",
            nombre_usuario="estudiante1",
            nombre="Juan Perez",
            cedula="1098765432",
            password="Password123!",
            rol=self.rol_estudiante,
            requiere_cambio_contrasena=False,
        )
        self.user_estudiante_2 = Usuario.objects.create_user(
            correo_institucional="estudiante2@unipamplona.edu.co",
            nombre_usuario="estudiante2",
            nombre="Maria Gomez",
            cedula="1098765433",
            password="Password123!",
            rol=self.rol_estudiante,
            requiere_cambio_contrasena=False,
        )
        self.user_docente = Usuario.objects.create_user(
            correo_institucional="director@unipamplona.edu.co",
            nombre_usuario="director",
            nombre="Prof. Carlos Ruiz",
            cedula="9876543210",
            password="Password123!",
            rol=self.rol_director,
            requiere_cambio_contrasena=False,
        )
        self.user_admo = Usuario.objects.create_user(
            correo_institucional="admo@unipamplona.edu.co",
            nombre_usuario="admo",
            nombre="Administrador General",
            cedula="9988776655",
            password="Password123!",
            rol=self.rol_admin,
            requiere_cambio_contrasena=False,
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
        self.assertContains(res, "Mi propuesta")
        self.assertNotContains(res, "Cargar el proyecto en la UP")
        url_descarga = reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk])
        self.assertContains(res, f'href="{url_descarga}"')
        self.assertNotContains(res, "Descarga no disponible por ahora")

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

    def test_enlace_subido_en_up_aparece_solo_con_propuesta_aprobada(self):
        """El enlace 'Subido en UP' (cargue_up:aviso_propuesta_confirmacion) aparece con propuesta Aprobada y no en otro estado."""
        # 1. Con propuesta Aprobada (user_estudiante_1): aparece el enlace y la tarjeta
        self.client.force_login(self.user_estudiante_1)
        res_aprobada = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res_aprobada.status_code, 200)
        url_aviso_1 = reverse("cargue_up:aviso_propuesta_confirmacion", args=[self.propuesta_1.pk])
        self.assertContains(res_aprobada, url_aviso_1)
        self.assertContains(res_aprobada, "Subido en UP")
        self.assertContains(res_aprobada, "Avisar a tu Director")

        # 2. Con propuesta En revisión (user_estudiante_2): NO aparece
        self.client.force_login(self.user_estudiante_2)
        res_revision = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res_revision.status_code, 200)
        url_aviso_2 = reverse("cargue_up:aviso_propuesta_confirmacion", args=[self.propuesta_2.pk])
        self.assertNotContains(res_revision, url_aviso_2)
        self.assertNotContains(res_revision, "Avisar a tu Director")

        # 3. Con propuesta en Subido en UP: NO aparece
        self.propuesta_1.estado = EstadoTramite.SUBIDO_EN_UP
        self.propuesta_1.save(update_fields=["estado"])
        self.client.force_login(self.user_estudiante_1)
        res_subido = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res_subido.status_code, 200)
        self.assertNotContains(res_subido, url_aviso_1)
        self.assertNotContains(res_subido, "Avisar a tu Director")

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

    def test_ir_up_con_propuesta_en_revision_queda_bloqueado(self):
        """BTN-IR-UP / EX-03: con la propuesta En revisión no redirige a la UP y queda auditado Bloqueado."""
        Parametro.objects.create(
            clave="url_up",
            valor="https://portal.unipamplona.edu.co/plataforma",
            descripcion="URL de la UP",
            usuario_actualizacion=self.user_admo,
        )

        # propuesta_2 (En revisión) pertenece al estudiante 2
        self.client.force_login(self.user_estudiante_2)
        res = self.client.get(reverse("cargue_up:ir_a_up", args=[self.propuesta_2.pk]))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("cargue_up:cargue_propuesta"))
        self.assertNotIn("portal.unipamplona.edu.co", res.url)

        auditoria = Auditoria.objects.filter(
            accion="Ir a la Plataforma UP",
            id_registro_afectado=self.propuesta_2.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.resultado, "Bloqueado")

        # El mensaje MSG-03-06 se muestra en la pantalla de cargue
        res_inicio = self.client.get(res.url)
        self.assertContains(res_inicio, MSG_03_06)

    # ==========================================================================
    # 3b. PRUEBAS DE DESCARGA DE PROPUESTA (B1c · PDF AL VUELO Y VALIDACIONES)
    # ==========================================================================

    def test_descargar_propuesta_aprobada_entrega_pdf_con_sus_datos_y_audita_exito(self):
        """B1c: Con propuesta Aprobada, entrega Propuesta_<código>.pdf con sus datos y audita Éxito."""
        self.propuesta_1.entidad = "Fundación Semillas del Norte"
        self.propuesta_1.objetivos = "Brindar formación tecnológica a líderes barriales"
        self.propuesta_1.save(update_fields=["entidad", "objetivos"])

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk]))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertEqual(
            res["Content-Disposition"],
            f'attachment; filename="Propuesta_{self.propuesta_1.codigo}.pdf"',
        )

        pdf_bytes = b"".join(res.streaming_content)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

        lector = PdfReader(BytesIO(pdf_bytes))
        texto_pdf = "\n".join((p.extract_text() or "") for p in lector.pages)
        self.assertIn(self.propuesta_1.codigo, texto_pdf)
        self.assertIn("Juan Perez", texto_pdf)
        self.assertIn("Ingeniería de Sistemas", texto_pdf)
        self.assertIn("2026-2", texto_pdf)
        self.assertIn("Sistema de Gestión Comunitaria", texto_pdf)
        self.assertIn("Fundación Semillas del Norte", texto_pdf)
        self.assertIn("Brindar formación tecnológica a líderes barriales", texto_pdf)

        auditoria = Auditoria.objects.filter(
            accion="Descargar propuesta",
            id_registro_afectado=self.propuesta_1.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.usuario, self.user_estudiante_1)
        self.assertEqual(auditoria.resultado, "Éxito")

    def test_descargar_con_propuesta_en_borrador_queda_bloqueada(self):
        """B1c: Con la propuesta en Borrador, la descarga sigue bloqueada y auditada como Bloqueado."""
        self.propuesta_1.estado = EstadoTramite.BORRADOR
        self.propuesta_1.save(update_fields=["estado"])

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk]))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("cargue_up:cargue_propuesta"))

        auditoria = Auditoria.objects.filter(
            accion="Descargar propuesta",
            id_registro_afectado=self.propuesta_1.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.resultado, "Bloqueado")

        res_inicio = self.client.get(res.url)
        self.assertContains(res_inicio, MSG_03_06)

    def test_descargar_con_propuesta_subido_en_up_queda_bloqueado(self):
        """BTN-DESCARGAR: «Solo con Aprobado». En Subido en UP la descarga queda bloqueada y auditada."""
        self.propuesta_1.estado = EstadoTramite.SUBIDO_EN_UP
        self.propuesta_1.save(update_fields=["estado"])

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk]))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("cargue_up:cargue_propuesta"))

        auditoria = Auditoria.objects.filter(
            accion="Descargar propuesta",
            id_registro_afectado=self.propuesta_1.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.resultado, "Bloqueado")

    def test_descargar_propuesta_si_generacion_falla_muestra_msg_03_04_y_audita_fallo(self):
        """B1c: Si generar_pdf_propuesta falla, muestra MSG-03-04 y registra auditoría con resultado Fallo."""
        self.client.force_login(self.user_estudiante_1)

        with (
            patch(
                "apps.cargue_up.views.cargue_propuesta.generar_pdf_propuesta",
                side_effect=RuntimeError("Error simulado al construir PDF"),
            ),
            self.assertLogs("apps.cargue_up.views.cargue_propuesta", level="ERROR"),
        ):
            res = self.client.get(reverse("cargue_up:descargar_propuesta", args=[self.propuesta_1.pk]))

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, reverse("cargue_up:cargue_propuesta"))

        auditoria = Auditoria.objects.filter(
            accion="Descargar propuesta",
            id_registro_afectado=self.propuesta_1.pk,
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertEqual(auditoria.resultado, "Fallo")

        res_inicio = self.client.get(res.url)
        self.assertContains(res_inicio, MSG_03_04)

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
        self.assertEqual(notificacion_1.mensaje, MSG_03_03)

        # La propuesta 2 está en revisión, NO debe recibir recordatorio
        notificacion_2 = Notificacion.objects.filter(
            propuesta=self.propuesta_2,
            tipo="RECORDATORIO_CARGUE_UP",
        ).first()
        self.assertIsNone(notificacion_2)

    # ==========================================================================
    # 5. PRUEBAS DE AJUSTES DE PANTALLA Y ESTADOS REALES (TAREA E9)
    # ==========================================================================

    def test_aprobado_en_up_muestra_estado_y_alerta_sin_a_la_espera(self):
        """E9-1: Aprobado en UP muestra su etiqueta y alerta MSG-05-03, sin 'Cargado en UP' ni 'a la espera'."""
        self.propuesta_1.estado = EstadoTramite.APROBADO_EN_UP
        self.propuesta_1.save(update_fields=["estado"])
        CargueUp.objects.create(
            propuesta=self.propuesta_1,
            director=self.director,
            fecha_declaracion=timezone.now() - timedelta(days=2),
            estado_verificacion=EstadoVerificacion.APROBADO_EN_UP,
            fecha_verificacion=timezone.now() - timedelta(days=1),
        )

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:cargue_propuesta"))

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Aprobado en UP")
        self.assertContains(res, "Tu Director revisó la Plataforma UP: Aprobado en UP.")
        self.assertNotContains(res, "Cargado en UP")
        self.assertNotContains(res, "a la espera")

    def test_subido_en_up_muestra_title_etapa_completada_sin_cuando_sea_aprobada(self):
        """E9-3: En Subido en UP ambos botones indican 'Etapa de cargue completada' con y sin url_up configurada."""
        self.propuesta_1.estado = EstadoTramite.SUBIDO_EN_UP
        self.propuesta_1.save(update_fields=["estado"])
        CargueUp.objects.create(
            propuesta=self.propuesta_1,
            fecha_declaracion=timezone.now() - timedelta(hours=2),
            estado_verificacion=EstadoVerificacion.PENDIENTE,
        )

        boton_descargar = (
            '<button type="button" class="btn btn-up-outline" disabled title="Etapa de cargue completada">'
            '<i class="bi bi-download"></i>Descargar propuesta'
            "</button>"
        )
        boton_ir_up = (
            '<button type="button" class="btn btn-up-primary" disabled title="Etapa de cargue completada">'
            '<i class="bi bi-box-arrow-up-right"></i>Ir a la Plataforma UP'
            "</button>"
        )

        self.client.force_login(self.user_estudiante_1)

        # 1. Sin url_up configurada
        Parametro.objects.filter(clave="url_up").delete()
        with self.subTest(url_up_configurada=False):
            res_sin_url = self.client.get(reverse("cargue_up:cargue_propuesta"))
            self.assertEqual(res_sin_url.status_code, 200)
            self.assertContains(res_sin_url, 'title="Etapa de cargue completada"', count=2)
            self.assertContains(res_sin_url, boton_descargar, html=True)
            self.assertContains(res_sin_url, boton_ir_up, html=True)
            self.assertNotContains(res_sin_url, "cuando sea aprobada")
            self.assertNotContains(res_sin_url, MSG_03_05)

        # 2. Con url_up configurada
        Parametro.objects.create(
            clave="url_up",
            valor="https://portal.unipamplona.edu.co/plataforma",
            descripcion="URL de la UP",
            usuario_actualizacion=self.user_admo,
        )
        with self.subTest(url_up_configurada=True):
            res_con_url = self.client.get(reverse("cargue_up:cargue_propuesta"))
            self.assertEqual(res_con_url.status_code, 200)
            self.assertContains(res_con_url, 'title="Etapa de cargue completada"', count=2)
            self.assertContains(res_con_url, boton_descargar, html=True)
            self.assertContains(res_con_url, boton_ir_up, html=True)
            self.assertNotContains(res_con_url, "cuando sea aprobada")
            self.assertNotContains(res_con_url, MSG_03_05)

    def test_fecha_aprobacion_se_conserva_tras_rechazado_en_up(self):
        """E9-2a: Cuando el Director rechaza en UP (Subido en UP / Aprobado en UP -> Aprobado), se conserva la fecha original."""
        fecha_original = timezone.now() - timedelta(days=10)
        HistorialEstado.objects.filter(propuesta=self.propuesta_1).update(fecha_hora=fecha_original)

        # Transición posterior desde Subido en UP -> Aprobado (al marcar Rechazado en UP)
        HistorialEstado.objects.create(
            propuesta=self.propuesta_1,
            usuario=self.user_docente,
            estado_anterior=EstadoTramite.SUBIDO_EN_UP,
            estado_nuevo=EstadoTramite.APROBADO,
            tipo_accion="verificacion_propuesta",
            fecha_hora=timezone.now() - timedelta(days=1),
        )
        # Y también una corrección desde Aprobado en UP -> Aprobado
        HistorialEstado.objects.create(
            propuesta=self.propuesta_1,
            usuario=self.user_docente,
            estado_anterior=EstadoTramite.APROBADO_EN_UP,
            estado_nuevo=EstadoTramite.APROBADO,
            tipo_accion="correccion_verif_propuesta",
            fecha_hora=timezone.now(),
        )
        CargueUp.objects.create(
            propuesta=self.propuesta_1,
            director=self.director,
            fecha_declaracion=timezone.now() - timedelta(days=2),
            estado_verificacion=EstadoVerificacion.RECHAZADO_EN_UP,
            fecha_verificacion=timezone.now(),
            observacion="Documento ilegible.",
        )

        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:cargue_propuesta"))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["fecha_aprobacion"], fecha_original)
        fecha_original_txt = timezone.localtime(fecha_original).strftime("%d/%m/%Y")
        self.assertContains(res, fecha_original_txt)

    def test_propuesta_aprobada_sin_historial_muestra_guion_y_no_pendiente(self):
        """E9-2b: Si la propuesta ya está Aprobada, Subido en UP o Aprobado en UP sin historial de fecha, muestra '—' y no 'Pendiente'."""
        HistorialEstado.objects.filter(propuesta=self.propuesta_1).delete()

        for estado in (
            EstadoTramite.APROBADO,
            EstadoTramite.SUBIDO_EN_UP,
            EstadoTramite.APROBADO_EN_UP,
        ):
            with self.subTest(estado=estado):
                self.propuesta_1.estado = estado
                self.propuesta_1.save(update_fields=["estado"])
                self.client.force_login(self.user_estudiante_1)
                res = self.client.get(reverse("cargue_up:cargue_propuesta"))
                self.assertEqual(res.status_code, 200)
                self.assertIsNone(res.context["fecha_aprobacion"])
                self.assertNotContains(res, '<span class="project-info-value">Pendiente</span>', html=True)
                self.assertContains(res, '<span class="project-info-value">—</span>', html=True)

        # En cambio, una propuesta En revisión sin fecha sí muestra 'Pendiente'
        self.client.force_login(self.user_estudiante_2)
        res_rev = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertContains(res_rev, '<span class="project-info-value">Pendiente</span>', html=True)

    def test_cerrar_sesion_en_encabezado_existe_y_funciona(self):
        """E9-4: El encabezado incluye el formulario POST hacia usuarios:logout y al enviarlo cierra la sesión."""
        self.client.force_login(self.user_estudiante_1)
        res = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res.status_code, 200)

        url_logout = reverse("usuarios:logout")
        self.assertContains(res, f'action="{url_logout}"')
        self.assertContains(
            res,
            '<button type="submit" class="btn btn-outline-danger">Cerrar sesión</button>',
            html=True,
        )

        res_logout = self.client.post(url_logout)
        self.assertEqual(res_logout.status_code, 302)

        # Tras cerrar sesión, intentar abrir cargue_up redirige al login
        res_post_logout = self.client.get(reverse("cargue_up:cargue_propuesta"))
        self.assertEqual(res_post_logout.status_code, 302)
        self.assertIn("login", res_post_logout.url)
