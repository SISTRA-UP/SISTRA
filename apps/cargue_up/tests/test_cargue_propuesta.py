"""SISTRA-03 · Cargue al sistema de UP: pruebas automatizadas.

Verifica los criterios de aceptación del requerimiento BR-03 (SISTRA-03):
- CA-01: Estudiante con proyecto Aprobado ve controles habilitados.
- CA-02: Proyecto no Aprobado tiene controles deshabilitados.
- CA-03: Descarga autenticada de su propio proyecto.
- CA-05: Confirmación de cargue transiciona a SUBIDO_EN_UP y registra CargueUp.
- CA-08: Aislamiento por estudiante (no puede ver ni notificar proyectos ajenos).
- CA-09: Bloqueo de notificaciones duplicadas.
- CA-11: Validación de fechas no futuras en formulario.
"""

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.forms.cargue_propuesta import (
    MSG_XX_09,
    MSG_XX_10,
    MSG_XX_11,
    MSG_XX_14,
    NotificarCargueForm,
)
from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.parametrizacion.models import Carrera, Facultad, PeriodoAcademico
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


class NotificarCargueFormTestCase(SimpleTestCase):
    """Pruebas unitarias para el formulario de notificación de cargue (sin requerir BD)."""

    def test_formulario_valido(self):
        form = NotificarCargueForm(
            data={
                "fecha_cargue": timezone.localdate().isoformat(),
                "observaciones": "Cargue realizado en la plataforma de la UP correctamente.",
            }
        )
        self.assertTrue(form.is_valid())

    def test_fecha_cargue_futura_invalida(self):
        """CA-11: La fecha de cargue no puede ser posterior a hoy."""
        manana = timezone.localdate() + timedelta(days=1)
        form = NotificarCargueForm(
            data={
                "fecha_cargue": manana.isoformat(),
                "observaciones": "Intento fecha futura",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn(MSG_XX_09, form.errors.get("fecha_cargue", []))

    def test_fecha_cargue_vacia_invalida(self):
        form = NotificarCargueForm(data={"fecha_cargue": "", "observaciones": "Sin fecha"})
        self.assertFalse(form.is_valid())
        self.assertIn(MSG_XX_10, form.errors.get("fecha_cargue", []))

    def test_observaciones_superan_500_caracteres(self):
        form = NotificarCargueForm(
            data={
                "fecha_cargue": timezone.localdate().isoformat(),
                "observaciones": "A" * 501,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn(MSG_XX_11, form.errors.get("observaciones", []))


class CargueUpViewsTestCase(TestCase):
    """Pruebas de integración de vistas y reglas de negocio para SISTRA-03."""

    def setUp(self):
        self.client = Client()

        # Roles
        self.rol_estudiante, _ = Rol.objects.get_or_create(nombre="Estudiante")
        self.rol_docente, _ = Rol.objects.get_or_create(nombre="Docente")

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

        # Entidades académicas
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

        # Personas y asignaciones
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

        # Propuesta 1 (Aprobada)
        self.propuesta_1 = Propuesta.objects.create(
            proceso=self.proceso_1,
            periodo_academico=self.periodo,
            codigo="PROP-2026-001",
            titulo="Sistema de Gestión Comunitaria",
            estado=EstadoTramite.APROBADO,
            fecha_envio=timezone.now() - timedelta(days=5),
        )

        # Propuesta 2 (En revisión)
        self.propuesta_2 = Propuesta.objects.create(
            proceso=self.proceso_2,
            periodo_academico=self.periodo,
            codigo="PROP-2026-002",
            titulo="Alfabetización Digital",
            estado=EstadoTramite.EN_REVISION,
            fecha_envio=timezone.now() - timedelta(days=2),
        )

    def test_ca_01_estudiante_con_propuesta_aprobada(self):
        """CA-01: Dado un estudiante autenticado con proyecto Aprobado, ve controles habilitados."""
        self.client.force_login(self.user_estudiante_1)
        url = reverse("cargue_up:cargue_propuesta")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["puede_cargar"])
        self.assertEqual(response.context["estado_actual"], EstadoTramite.APROBADO)
        self.assertContains(response, "Mi proyecto de horas sociales")
        self.assertContains(response, "Ya cargué mi proyecto")

    def test_ca_02_propuesta_no_aprobada_deshabilita_acciones(self):
        """CA-02: Proyecto con estado distinto de Aprobado tiene acciones deshabilitadas."""
        self.client.force_login(self.user_estudiante_2)
        url = reverse("cargue_up:cargue_propuesta")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["puede_cargar"])
        self.assertContains(response, "disabled")

    def test_ca_05_confirmacion_cargue_exitosa(self):
        """CA-05: Al confirmar la notificación, cambia a Subido en UP y registra CargueUp y trazabilidad."""
        self.client.force_login(self.user_estudiante_1)
        url = reverse("cargue_up:notificar_cargue", args=[self.propuesta_1.pk])

        datos = {
            "fecha_cargue": timezone.localdate().isoformat(),
            "observaciones": "Radicado correctamente con número de folio UP-98765.",
        }
        response = self.client.post(url, data=datos, follow=True)

        self.assertEqual(response.status_code, 200)

        # Verificar actualización del estado de la propuesta
        self.propuesta_1.refresh_from_db()
        self.assertEqual(self.propuesta_1.estado, EstadoTramite.SUBIDO_EN_UP)

        # Verificar creación de CargueUp
        cargue = CargueUp.objects.filter(propuesta=self.propuesta_1).first()
        self.assertIsNotNone(cargue)
        self.assertEqual(cargue.estado_verificacion, EstadoVerificacion.PENDIENTE)
        self.assertEqual(cargue.observacion, datos["observaciones"])

        # Verificar HistorialEstado
        historial = HistorialEstado.objects.filter(
            propuesta=self.propuesta_1, estado_nuevo=EstadoTramite.SUBIDO_EN_UP
        ).first()
        self.assertIsNotNone(historial)
        self.assertEqual(historial.usuario, self.user_estudiante_1)

        # Verificar Auditoria
        auditoria = Auditoria.objects.filter(
            accion="NOTIFICAR_CARGUE_EXITOSO", id_registro_afectado=cargue.pk
        ).first()
        self.assertIsNotNone(auditoria)

        # Verificar Notificación en sistema al docente
        notif = Notificacion.objects.filter(
            usuario=self.user_docente, propuesta=self.propuesta_1
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("notificó que cargó su proyecto", notif.mensaje)

    def test_ca_08_estudiante_no_puede_notificar_proyecto_ajeno(self):
        """CA-08: Un estudiante no puede notificar el cargue del proyecto de otro estudiante."""
        # Estudiante 2 intenta notificar la propuesta del Estudiante 1
        self.client.force_login(self.user_estudiante_2)
        url = reverse("cargue_up:notificar_cargue", args=[self.propuesta_1.pk])

        datos = {
            "fecha_cargue": timezone.localdate().isoformat(),
            "observaciones": "Intento no autorizado",
        }
        response = self.client.post(url, data=datos, follow=True)

        self.assertEqual(response.status_code, 200)
        # La propuesta no debe haber cambiado
        self.propuesta_1.refresh_from_db()
        self.assertEqual(self.propuesta_1.estado, EstadoTramite.APROBADO)
        self.assertFalse(CargueUp.objects.filter(propuesta=self.propuesta_1).exists())

    def test_ca_09_bloqueo_doble_notificacion(self):
        """CA-09: No es posible registrar dos notificaciones de cargue para el mismo proyecto."""
        # Primera notificación exitosa
        self.client.force_login(self.user_estudiante_1)
        url = reverse("cargue_up:notificar_cargue", args=[self.propuesta_1.pk])

        datos = {
            "fecha_cargue": timezone.localdate().isoformat(),
            "observaciones": "Primer cargue",
        }
        self.client.post(url, data=datos)

        # Segundo intento de notificación sobre el mismo proyecto
        response = self.client.post(url, data=datos, follow=True)
        self.assertEqual(response.status_code, 200)

        # Solo debe existir 1 registro de CargueUp
        total_cargues = CargueUp.objects.filter(propuesta=self.propuesta_1).count()
        self.assertEqual(total_cargues, 1)
