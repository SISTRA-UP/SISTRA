"""Integration test for reopening a saved proposal with date fields.
Ensures the rendered HTML contains the expected ISO date values.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.usuarios.models import User
from apps.personas.models import Estudiante, Inscripcion, EstadoInscripcion, Carrera
from apps.propuestas.models import Propuesta, EstadoTramite, ProcesoTrabajoSocial

class MiPropuestaDatePersistenceTest(TestCase):
    def setUp(self):
        # Create demo student user
        self.user = User.objects.create_user(
            username='demo.estudiante',
            email='demo.estudiante@unipamplona.edu.co',
            password='Demo1234!'
        )
        self.carrera = Carrera.objects.create(nombre='Trabajo Social')
        self.estudiante = Estudiante.objects.create(usuario=self.user)
        self.inscripcion = Inscripcion.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            estado=EstadoInscripcion.ACTIVO,
        )
        # Create proceso asociado al estudiante
        self.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante=self.estudiante,
            estudiante_carrera=self.inscripcion,
        )
        # Create a proposal with dates saved
        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            titulo='Demo',
            entidad='Demo Entidad',
            sector_entidad='Público',
            sector='Social',
            zona='Urbana',
            area='Área 1',
            unidad='Unidad 1',
            poblacion_beneficiada='100',
            identificacion_poblacion='ID',
            resena_historica='Hist',
            identificacion_necesidad='Necesidad',
            justificacion='Just',
            objetivos='Obj',
            referente_teorico='Teoria',
            propuesta_social='Social',
            impacto_social='Impacto',
            fecha_inicio=timezone.datetime(2026, 12, 1).date(),
            fecha_fin=timezone.datetime(2026, 12, 31).date(),
            estado=EstadoTramite.BORRADOR,
        )
        self.client = Client()
        self.client.login(username='demo.estudiante', password='Demo1234!')

    def test_dates_rendered_on_reopen(self):
        url = reverse('propuestas:montaje')  # URL name defined in urls.py
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # The date inputs should contain the saved ISO values
        self.assertContains(response, 'value="2026-12-01"')
        self.assertContains(response, 'value="2026-12-31"')
