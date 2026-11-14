"""SISTRA-01 · Montaje de propuesta – Trabajo Social: pruebas unitarias.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""
from datetime import timedelta
from io import BytesIO
import zipfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import (
    Carrera,
    EstadoPeriodo,
    Facultad,
    PeriodoAcademico,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.forms.montaje import (
    CAMPOS_OBLIGATORIOS_ENVIO,
    CargaPlantillaWordForm,
    PropuestaMontajeForm,
)
from apps.propuestas.models import EstadoTramite, Propuesta, SectorEntidad
from apps.propuestas.services.montaje import extraer_datos_plantilla
from apps.seguimiento.models import HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()


class BaseMontajeTestCase(TestCase):
    """Configuración base para las pruebas de montaje de propuestas."""

    def setUp(self):
        super().setUp()
        hoy = timezone.localdate()

        # Roles
        self.rol_estudiante, _ = Rol.objects.get_or_create(nombre='Estudiante')
        self.rol_director, _ = Rol.objects.get_or_create(nombre='Director')

        # Estructura institucional
        self.facultad = Facultad.objects.create(
            nombre='Facultad de Ingenierías y Arquitectura', estado=Estado.ACTIVO
        )
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería de Sistemas',
            codigo='SIS-136',
            estado=Estado.ACTIVO,
        )

        # Periodo académico
        self.periodo = PeriodoAcademico.objects.create(
            nombre='2026-2',
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin=hoy + timedelta(days=120),
            fecha_cierre_propuesta=hoy + timedelta(days=40),
            fecha_cierre_informe=hoy + timedelta(days=100),
            estado=EstadoPeriodo.VIGENTE,
        )

        # Director
        self.user_director = Usuario.objects.create_user(
            correo_institucional='director.montaje@unipamplona.edu.co',
            password='Password123!',
            nombre='Dra. Directora de Sistemas',
            cedula='1098555001',
            nombre_usuario='director.montaje',
            rol=self.rol_director,
        )
        self.director = Director.objects.create(usuario=self.user_director)
        self.asignacion_director = DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=hoy - timedelta(days=60),
            activo=True,
        )

        # Estudiante
        self.user_estudiante = Usuario.objects.create_user(
            correo_institucional='estudiante.montaje@unipamplona.edu.co',
            password='Password123!',
            nombre='Estudiante Deyson',
            cedula='1098555002',
            nombre_usuario='estudiante.montaje',
            rol=self.rol_estudiante,
        )
        self.estudiante = Estudiante.objects.create(usuario=self.user_estudiante)
        self.inscripcion = EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            fecha_registro=hoy - timedelta(days=20),
            estado=EstadoInscripcion.ACTIVO,
        )
        self.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion,
            fecha_inicio=timezone.now() - timedelta(days=15),
            estado=EstadoAvance.EN_CURSO,
        )


class TestMontajeVistasYFlujos(BaseMontajeTestCase):
    """Pruebas de endpoints GET y POST para el montaje de la propuesta."""

    def test_acceso_requiere_login(self):
        """Usuarios no autenticados son redirigidos al login."""
        url = reverse('propuestas:montaje')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_get_muestra_formulario_inicial_vacio(self):
        """Un estudiante sin propuesta ve el formulario de nueva propuesta."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Propuesta de Trabajo Social')
        self.assertContains(resp, 'Borrador')

    def test_guardar_borrador_parcial(self):
        """Un estudiante puede guardar un borrador con campos incompletos."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        data = {
            'accion': 'guardar',
            'titulo': 'Implementación de plataforma comunitaria',
            'entidad': 'Fundación Bienestar Social',
            'sector_entidad': SectorEntidad.PRIVADO,
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        propuesta = Propuesta.objects.filter(proceso=self.proceso).first()
        self.assertIsNotNone(propuesta)
        self.assertEqual(propuesta.titulo, 'Implementación de plataforma comunitaria')
        self.assertEqual(propuesta.estado, EstadoTramite.BORRADOR)

    def test_autoguardar_via_ajax(self):
        """El autoguardado asíncrono responde JSON con estado y porcentaje."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:autoguardar')
        data = {
            'titulo': 'Proyecto Social en Desarrollo',
            'entidad': 'Alcaldía Municipal',
        }
        resp = self.client.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        json_resp = resp.json()
        self.assertTrue(json_resp['ok'])
        self.assertEqual(json_resp['estado'], EstadoTramite.BORRADOR)
        self.assertGreaterEqual(json_resp['progreso'], 0)

    def test_enviar_incompleto_falla_validacion(self):
        """No se permite enviar la propuesta si no está al 100% de obligatorios."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        data = {
            'accion': 'enviar',
            'titulo': 'Proyecto Incompleto',
            # Faltan todos los demás campos obligatorios
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Para enviar la propuesta a revisión se deben completar todos los campos')

        # No debe haber pasado a EN_REVISION
        prop = Propuesta.objects.filter(proceso=self.proceso).first()
        if prop:
            self.assertNotEqual(prop.estado, EstadoTramite.EN_REVISION)

    def test_enviar_completo_exitoso_y_notifica(self):
        """Al completar todos los campos obligatorios, el envío pasa a EN_REVISION y notifica."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        hoy = timezone.localdate()

        data = {
            'accion': 'enviar',
            'titulo': 'Capacitación Digital en Comunidades Rurales',
            'entidad': 'Fundación Crecer',
            'sector_entidad': SectorEntidad.PRIVADO,
            'sector': 'Tecnología y Educación',
            'zona': 'Rural',
            'area': 'Desarrollo Comunitario',
            'unidad': 'Vereda El Porvenir',
            'poblacion_beneficiada': '80 familias campesinas',
            'identificacion_poblacion': 'Adultos y jóvenes con brecha digital',
            'resena_historica': 'La fundación opera desde 2018 impulsando la inclusión.',
            'identificacion_necesidad': 'Falta de acceso a competencias ofimáticas básicas.',
            'justificacion': 'Mejora las oportunidades de comercialización agrícola.',
            'objetivos': 'Capacitar a 80 personas en el uso de plataformas web y correo.',
            'referente_teorico': 'Teoría de adopción tecnológica comunitaria.',
            'propuesta_social': 'Talleres prácticos semanales de 4 horas.',
            'impacto_social': 'Inserción productiva y cierre de brecha digital local.',
            'fecha_inicio': str(hoy),
            'fecha_fin': str(hoy + timedelta(days=90)),
        }

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        propuesta = Propuesta.objects.get(proceso=self.proceso)
        self.assertEqual(propuesta.estado, EstadoTramite.EN_REVISION)
        self.assertIsNotNone(propuesta.fecha_envio)

        # Historial de estados registrado
        historial = HistorialEstado.objects.filter(propuesta=propuesta).latest('fecha_hora')
        self.assertEqual(historial.estado_nuevo, EstadoTramite.EN_REVISION)
        self.assertEqual(historial.usuario, self.user_estudiante)

        # Notificación al director de la carrera
        notif = Notificacion.objects.filter(
            usuario=self.user_director, propuesta=propuesta
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn('Capacitación Digital', notif.mensaje)

    def test_propuesta_en_revision_queda_bloqueada(self):
        """Cuando la propuesta está en revisión, la edición por el estudiante queda bloqueada."""
        hoy = timezone.localdate()
        propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo='PROP-TEST-BLOQ',
            titulo='Propuesta Bloqueada',
            estado=EstadoTramite.EN_REVISION,
            fecha_inicio=hoy,
            fecha_fin=hoy + timedelta(days=30),
        )

        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'se encuentra bloqueada para edición')

        # Intentar modificar por POST debe ser rechazado
        resp_post = self.client.post(url, {'accion': 'guardar', 'titulo': 'Cambio no permitido'})
        self.assertEqual(resp_post.status_code, 302)
        propuesta.refresh_from_db()
        self.assertEqual(propuesta.titulo, 'Propuesta Bloqueada')


class TestServicioPlantillaWord(TestCase):
    """Pruebas del parser de plantilla Word (.docx)."""

    def test_validador_rechaza_archivos_no_docx(self):
        form = CargaPlantillaWordForm(data={}, files={'archivo': BytesIO(b'contenido')})
        form.files['archivo'].name = 'documento.pdf'
        self.assertFalse(form.is_valid())
        self.assertIn('Solo se aceptan archivos Word con formato .docx.', form.errors['archivo'])

    def test_extraccion_desde_docx_xml_valido(self):
        """Genera un .docx mínimo en memoria con zipfile y valida extracción de campos."""
        buffer = BytesIO()
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Título de la propuesta: Alfabetización Digital Rural</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Entidad beneficiaria: Asociación Progresar</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Justificación: Necesidad sentida de la comunidad</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>'
        ).encode('utf-8')

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('word/document.xml', xml_content)

        buffer.seek(0)
        datos = extraer_datos_plantilla(buffer)
        self.assertEqual(datos.get('titulo'), 'Alfabetización Digital Rural')
        self.assertEqual(datos.get('entidad'), 'Asociación Progresar')
        self.assertEqual(datos.get('justificacion'), 'Necesidad sentida de la comunidad')
