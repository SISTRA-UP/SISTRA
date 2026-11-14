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
from apps.seguimiento.models import Auditoria
#  Importar las constantes desde aprobacion
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, RESULTADO_BLOQUEADO


TEXTO_VALIDO = 'A' * 100
TEXTO_CORTO = 'A' * 10
TEXTO_LARGO = 'A' * 1500


class MontajeInformeTests(TestCase):

    def setUp(self):
        self.client = Client()

        self.rol, _ = Rol.objects.get_or_create(
            nombre='Estudiante',
            defaults={'estado': 'Activo'}
        )

        self.usuario = Usuario.objects.create_user(
            correo_institucional='test@unipamplona.edu.co',
            nombre='Test User',
            cedula='12345678',
            nombre_usuario='test',
            password='testpass123',
            rol=self.rol,
            requiere_cambio_contrasena=False,
        )

        self.estudiante = Estudiante.objects.create(usuario=self.usuario)

        self.facultad, _ = Facultad.objects.get_or_create(nombre='Facultad Test')
        self.carrera, _ = Carrera.objects.get_or_create(
            nombre='Carrera Test',
            defaults={'facultad': self.facultad, 'codigo': 'CT-TEST-1'}
        )

        self.est_carr = EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            estado='Activo',
        )

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

        self.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.est_carr,
            fecha_inicio=timezone.now(),
            estado='En curso',
        )

        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo='PROP-TEST-1',
            titulo='Propuesta de Prueba',
            estado=EstadoTramite.APROBADO_EN_UP,
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

    def _login(self):
        self.client.force_login(self.usuario)

    def _crear_informe(self, estado):
        return Informe.objects.create(
            propuesta=self.propuesta,
            periodo_academico=self.periodo,
            codigo=f'INF-TEST-1-{estado[:3]}',
            estado=estado,
        )

    # ─── Pruebas de acceso ───

    def test_redireccion_si_no_hay_login(self):
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 302)

    def test_acceso_denegado_sin_propuesta_aprobada(self):
        self._login()
        self.propuesta.estado = EstadoTramite.BORRADOR
        self.propuesta.save()

        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Acceso no habilitado')

    def test_director_recibe_403(self):
        """Un usuario sin perfil de estudiante debe recibir 403."""
        rol_director, _ = Rol.objects.get_or_create(
            nombre='Director',
            defaults={'estado': 'Activo'}
        )
        usuario_director = Usuario.objects.create_user(
            correo_institucional='director@test.com',
            nombre='Director Test',
            cedula='9999999999',
            nombre_usuario='director',
            password='testpass123',
            rol=rol_director,
            requiere_cambio_contrasena=False,
        )
        self.client.force_login(usuario_director)

        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 403)

    def test_acceso_exitoso_con_propuesta_aprobada(self):
        self._login()
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Formulario de Informe')

    # ─── Pruebas de envío y bloqueo ───

    def test_enviar_informe_cambia_estado(self):
        self._login()
        data = {
            'accion': 'enviar',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)

        informe = Informe.objects.get(propuesta=self.propuesta)
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
        self.assertIsNotNone(informe.fecha_envio)

    def test_post_sobre_informe_en_revision_no_cambia_nada(self):
        """POST sobre informe En revisión queda auditado como Bloqueado."""
        self._login()
        informe = self._crear_informe(EstadoTramite.EN_REVISION)
        texto_original = informe.resultados

        data = {
            'accion': 'guardar_borrador',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)

        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(informe.resultados, texto_original)

        # ⬅️ Usar la constante importada
        auditoria = Auditoria.objects.filter(
            id_registro_afectado=informe.id_informe,
            resultado=RESULTADO_BLOQUEADO,
        ).exists()
        self.assertTrue(auditoria)

    def test_post_sobre_informe_aprobado_no_cambia_nada(self):
        self._login()
        informe = self._crear_informe(EstadoTramite.APROBADO)

        data = {
            'accion': 'guardar_borrador',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)

        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO)

    def test_formulario_bloqueado_si_esta_en_revision(self):
        self._login()
        self._crear_informe(EstadoTramite.EN_REVISION)

        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe bloqueado')

    # ─── Pruebas de borrador y reenvío ───

    def test_guardar_borrador_parcial(self):
        """Se puede guardar un borrador con solo 1 campo."""
        self._login()
        data = {
            'accion': 'guardar_borrador',
            'resultados': TEXTO_VALIDO,
            'conclusiones': '',
            'recomendaciones': '',
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)

        informe = Informe.objects.get(propuesta=self.propuesta)
        self.assertEqual(informe.estado, EstadoTramite.BORRADOR)
        self.assertEqual(informe.resultados, TEXTO_VALIDO)

    def test_guardar_borrador_no_cambia_estado_requiere_modificacion(self):
        """En Requiere modificación, guardar borrador mantiene el estado."""
        self._login()
        informe = self._crear_informe(EstadoTramite.REQUIERE_MODIFICACION)

        data = {
            'accion': 'guardar_borrador',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)

        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.REQUIERE_MODIFICACION)

    def test_reenvio_incrementa_version(self):
        """Reenviar desde Requiere modificación sube version_entrega a 2."""
        self._login()
        informe = self._crear_informe(EstadoTramite.REQUIERE_MODIFICACION)
        self.assertEqual(informe.version_entrega, 1)

        data = {
            'accion': 'enviar',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)

        informe.refresh_from_db()
        self.assertEqual(informe.version_entrega, 2)
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)

    # ─── Pruebas de informe rechazado ───

    def test_informe_rechazado_crea_nuevo(self):
        """Si el informe está Rechazado, se crea uno nuevo con código distinto."""
        self._login()
        rechazado = self._crear_informe(EstadoTramite.RECHAZADO)

        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)

        rechazado.refresh_from_db()
        self.assertEqual(rechazado.estado, EstadoTramite.RECHAZADO)

        nuevo = Informe.objects.filter(
            propuesta=self.propuesta,
            estado=EstadoTramite.BORRADOR,
        ).first()
        self.assertIsNotNone(nuevo)
        self.assertNotEqual(nuevo.codigo, rechazado.codigo)

    # ─── Pruebas de validación de texto ───

    def test_mas_de_1000_caracteres_se_rechaza(self):
        self._login()
        data = {
            'accion': 'guardar_borrador',
            'resultados': TEXTO_LARGO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Máximo')

    def test_menos_de_50_no_se_puede_enviar(self):
        self._login()
        data = {
            'accion': 'enviar',
            'resultados': TEXTO_CORTO,
            'conclusiones': TEXTO_CORTO,
            'recomendaciones': TEXTO_CORTO,
        }
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'mínimo 50 caracteres')

    # ─── Pruebas de auditoría ───

    def test_auditoria_al_crear_informe(self):
        self._login()
        self.client.get(reverse('informes:montaje'))

        informe = Informe.objects.filter(propuesta=self.propuesta).first()
        auditoria = Auditoria.objects.filter(
            id_registro_afectado=informe.id_informe,
            accion='Crear informe',
        ).exists()
        self.assertTrue(auditoria)

    def test_auditoria_al_guardar_borrador(self):
        self._login()
        data = {
            'accion': 'guardar_borrador',
            'resultados': TEXTO_VALIDO,
            'conclusiones': '',
            'recomendaciones': '',
        }
        self.client.post(reverse('informes:montaje'), data)

        informe = Informe.objects.filter(propuesta=self.propuesta).first()
        auditoria = Auditoria.objects.filter(
            id_registro_afectado=informe.id_informe,
            accion='Guardar borrador',
        ).exists()
        self.assertTrue(auditoria)

    def test_auditoria_al_enviar_informe(self):
        self._login()
        data = {
            'accion': 'enviar',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO,
        }
        self.client.post(reverse('informes:montaje'), data)

        informe = Informe.objects.filter(propuesta=self.propuesta).first()
        auditoria = Auditoria.objects.filter(
            id_registro_afectado=informe.id_informe,
            accion='Enviar informe',
        ).exists()
        self.assertTrue(auditoria)