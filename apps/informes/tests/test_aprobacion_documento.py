"""El documento del informe solo se sirve a su Director autorizado."""

from datetime import date
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.informes.models import Informe
from apps.parametrizacion.models import Carrera, Facultad, PeriodoAcademico
from apps.personas.models import Director, DirectorCarrera, Estudiante, EstudianteCarrera
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.forms.aprobacion import RESULTADO_BLOQUEADO, RESULTADO_EXITO, RESULTADO_FALLO
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Rol


class DocumentoInformeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        usuario = get_user_model()
        rol_director = Rol.objects.get(nombre='Director')

        def crear_usuario(nombre, rol):
            return usuario.objects.create_user(
                correo_institucional=f'{nombre}@example.com',
                nombre=nombre, cedula=f'7000{len(nombre)}',
                nombre_usuario=f'b1f_{nombre}', password='Prueba2026!',
                rol=rol, requiere_cambio_contrasena=False,
            )

        cls.director = crear_usuario('director_pdf', rol_director)
        cls.otro_director = crear_usuario('otro_director_pdf', rol_director)
        cls.estudiante = crear_usuario('estudiante_pdf', Rol.objects.get(nombre='Estudiante'))
        facultad = Facultad.objects.create(nombre='Facultad B1f')
        carrera = Carrera.objects.create(facultad=facultad, nombre='Carrera B1f', codigo='B1F-1')
        otra = Carrera.objects.create(facultad=facultad, nombre='Otra B1f', codigo='B1F-2')
        for director, asignada in ((cls.director, carrera), (cls.otro_director, otra)):
            DirectorCarrera.objects.create(
                director=Director.objects.create(usuario=director),
                carrera=asignada, fecha_inicio=timezone.localdate(), activo=True,
            )
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=Estudiante.objects.create(usuario=cls.estudiante),
            carrera=carrera, estado='Activo',
        )
        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion, fecha_inicio=timezone.now(), estado='En curso',
        )
        periodo = PeriodoAcademico.objects.create(
            nombre='Periodo B1f', fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31), fecha_cierre_propuesta=date(2026, 6, 30),
            fecha_cierre_informe=date(2026, 12, 15), estado='Cerrado',
        )
        propuesta = Propuesta.objects.create(
            proceso=proceso, periodo_academico=periodo,
            codigo='PROP-B1F', titulo='Propuesta B1f', estado=EstadoTramite.APROBADO_EN_UP,
        )
        cls.informe = Informe.objects.create(
            propuesta=propuesta, periodo_academico=periodo,
            codigo='INF-B1F', resultados='Resultados visibles',
            conclusiones='Conclusiones', recomendaciones='Recomendaciones',
            estado=EstadoTramite.EN_REVISION, fecha_envio=timezone.now(),
        )

    def setUp(self):
        self.url = reverse('informes:documento', kwargs={'id_informe': self.informe.pk})

    def test_director_visualiza_y_descarga_el_pdf_oficial(self):
        self.client.force_login(self.director)
        pagina = self.client.get(reverse('informes:aprobacion'))
        self.assertContains(pagina, self.url)

        vista = self.client.get(self.url)
        descarga = self.client.get(self.url, {'descargar': '1'})
        self.assertEqual(vista.status_code, 200)
        self.assertEqual(vista['Content-Type'], 'application/pdf')
        self.assertIn('inline', vista['Content-Disposition'])
        self.assertIn('attachment', descarga['Content-Disposition'])
        self.assertIn('informe_INF-B1F.pdf', descarga['Content-Disposition'])
        for respuesta in (vista, descarga):
            self.assertTrue(respuesta.content.startswith(b'%PDF-'))
            texto = ' '.join(
                pagina.extract_text() or ''
                for pagina in PdfReader(BytesIO(respuesta.content)).pages
            )
            for campo in ('INF-B1F', 'estudiante_pdf', 'Resultados visibles',
                          'Conclusiones', 'Recomendaciones'):
                self.assertIn(campo, texto)
        self.assertEqual(Auditoria.objects.filter(
            accion='documento_informe', resultado=RESULTADO_EXITO,
            id_registro_afectado=self.informe.pk,
        ).count(), 2)

    @patch('apps.informes.views.aprobacion.generar_pdf_informe')
    def test_director_de_otra_carrera_recibe_404_sin_generar_pdf(self, generar):
        self.client.force_login(self.otro_director)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 404)
        generar.assert_not_called()
        self.assertTrue(Auditoria.objects.filter(
            accion='intento_documento_informe', resultado=RESULTADO_BLOQUEADO,
            id_registro_afectado=self.informe.pk,
        ).exists())

    def test_sin_sesion_redirige_y_estudiante_recibe_403(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.estudiante)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    @patch('apps.informes.views.aprobacion.generar_pdf_informe', side_effect=RuntimeError('interno'))
    def test_documento_no_disponible_se_informa_y_audita(self, generar):
        self.client.force_login(self.director)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 503)
        self.assertContains(respuesta, 'El documento del informe no está disponible.', status_code=503)
        self.assertNotContains(respuesta, 'interno', status_code=503)
        self.assertTrue(Auditoria.objects.filter(
            accion='intento_documento_informe', resultado=RESULTADO_FALLO,
            id_registro_afectado=self.informe.pk,
        ).exists())

    @patch('apps.informes.views.aprobacion.generar_pdf_informe', return_value=b'no es un PDF')
    def test_generador_con_respuesta_invalida_muestra_documento_no_disponible(self, generar):
        self.client.force_login(self.director)
        respuesta = self.client.get(self.url)
        self.assertContains(
            respuesta, 'El documento del informe no está disponible.', status_code=503,
        )
        self.assertTrue(Auditoria.objects.filter(
            accion='intento_documento_informe', resultado=RESULTADO_FALLO,
            id_registro_afectado=self.informe.pk,
        ).exists())

    def test_informe_archivado_no_se_puede_consultar(self):
        self.informe.archivado = True
        self.informe.save(update_fields=['archivado'])
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(self.url).status_code, 404)
