"""Pruebas unitarias para el montaje de informe (SISTRA-06)."""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import date

from apps.usuarios.models import Usuario, Rol
from apps.personas.models import Estudiante, EstudianteCarrera
from apps.parametrizacion.models import Facultad, Carrera, PeriodoAcademico, EstadoPeriodo
from apps.propuestas.models import Propuesta, EstadoTramite
from apps.procesos.models import ProcesoTrabajoSocial
from apps.informes.models import Informe


class MontajeInformeTests(TestCase):
    """Pruebas para la vista de montaje de informe del estudiante."""

    def setUp(self):
        """Configuración inicial: crea un estudiante con propuesta Aprobado en UP."""
        self.client = Client()

        # 1. Crear o obtener Rol
        self.rol, _ = Rol.objects.get_or_create(
            nombre='Estudiante',
            defaults={'estado': 'Activo'}
        )

        # 2. Crear Usuario (con requiere_cambio_contrasena=False para evitar redirecciones)
        self.usuario = Usuario.objects.create_user(
            correo_institucional='test@unipamplona.edu.co',
            nombre='Test User',
            cedula='12345678',
            nombre_usuario='test',
            password='testpass123',
            rol=self.rol,
            requiere_cambio_contrasena=False,  # ⬅️ CLAVE: evita que el middleware redirija
        )

        # 3. Crear Estudiante
        self.estudiante = Estudiante.objects.create(usuario=self.usuario)

        # 4. Crear Facultad y Carrera
        self.facultad, _ = Facultad.objects.get_or_create(nombre='Facultad Test')
        self.carrera, _ = Carrera.objects.get_or_create(
            nombre='Carrera Test',
            defaults={'facultad': self.facultad, 'codigo': 'CT-TEST-1'}
        )

        # 5. Crear Inscripción (estudiante_carrera)
        self.est_carr = EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            estado='Activo',
        )

        # 6. Crear Periodo Académico (CERRADO para no chocar con el vigente local)
        self.periodo, _ = PeriodoAcademico.objects.get_or_create(
            nombre='2026-TEST',
            defaults={
                'fecha_inicio': date(2026, 1, 1),
                'fecha_fin': date(2026, 6, 30),
                'fecha_cierre_propuesta': date(2026, 3, 1),
                'fecha_cierre_informe': date(2026, 6, 1),
                'estado': EstadoPeriodo.CERRADO,
            }
        )

        # 7. Crear Proceso
        self.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.est_carr,
            fecha_inicio=timezone.now(),
            estado='En curso',
        )

        # 8. Crear Propuesta en estado APROBADO_EN_UP
        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo='PROP-TEST-1',
            titulo='Propuesta de Prueba',
            estado=EstadoTramite.APROBADO_EN_UP,
            # Campos obligatorios del modelo Propuesta
            resena_historica='x',
            identificacion_necesidad='x',
            justificacion='x',
            objetivos='x',
            referente_teorico='x',
            impacto_social='x',
            identificacion_poblacion='x',
            propuesta_social='x',
            entidad='x',
            poblacion_beneficiada='x',
            zona='x',
            area='x',
            sector='x',
            unidad='x',
        )

    def test_redireccion_si_no_hay_login(self):
        """Si no está logueado, debe redirigir al login."""
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 302)

    def test_acceso_denegado_sin_propuesta_aprobada(self):
        """Si la propuesta no está en Aprobado en UP, debe mostrar mensaje de error."""
        # ⬅️ force_login bypassa el middleware de cambio de contraseña
        self.client.force_login(self.usuario)

        # Cambiamos el estado a Borrador para simular que no cumple el requisito
        self.propuesta.estado = EstadoTramite.BORRADOR
        self.propuesta.save()

        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Acceso no habilitado')

    def test_acceso_exitoso_con_propuesta_aprobada(self):
        """Si tiene propuesta Aprobado en UP, debe cargar el formulario."""
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('informes:montaje'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Formulario de Informe')

    def test_enviar_informe_cambia_estado(self):
        """Al enviar el informe con los 3 campos llenos, debe pasar a En revisión."""
        self.client.force_login(self.usuario)

        data = {
            'accion': 'enviar',
            'resultados': 'Resultados de prueba',
            'conclusiones': 'Conclusiones de prueba',
            'recomendaciones': 'Recomendaciones de prueba',
        }
        response = self.client.post(reverse('informes:montaje'), data)

        # Debe redirigir después de enviar
        self.assertEqual(response.status_code, 302)

        # Verificar que el informe se creó y cambió de estado
        informe = Informe.objects.get(propuesta=self.propuesta)
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
        self.assertIsNotNone(informe.fecha_envio)

    def test_formulario_bloqueado_si_esta_en_revision(self):
        """Si el informe ya está en revisión, no se puede editar (bloqueado)."""
        self.client.force_login(self.usuario)

        # Creamos un informe manualmente en estado En revisión
        Informe.objects.create(
            propuesta=self.propuesta,
            periodo_academico=self.periodo,
            codigo='INF-TEST-1',
            estado=EstadoTramite.EN_REVISION,
        )

        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe bloqueado')