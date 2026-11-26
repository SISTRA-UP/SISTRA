"""Pruebas de generación de PDF del informe (B1b)."""
import io
from datetime import date
from django.test import TestCase
from django.utils import timezone
from pypdf import PdfReader

from apps.informes.models import Informe
from apps.parametrizacion.models import Carrera, EstadoPeriodo, Facultad, PeriodoAcademico
from apps.personas.models import Estudiante, EstudianteCarrera
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.reportes.services.report_pdf_service import _texto_seguro
from apps.usuarios.models import Rol, Usuario
from apps.informes.services.documento_pdf import generar_pdf_informe


class TestGenerarPDFInforme(TestCase):
    """Pruebas de la función generar_pdf_informe."""

    def setUp(self):
        self.rol, _ = Rol.objects.get_or_create(nombre='Estudiante', defaults={'estado': 'Activo'})
        self.usuario = Usuario.objects.create_user(
            correo_institucional='pdf@unipamplona.edu.co', nombre='PDF Test',
            cedula='7777777777', nombre_usuario='pdftest', password='testpass123',
            rol=self.rol, requiere_cambio_contrasena=False,
        )
        self.estudiante = Estudiante.objects.create(usuario=self.usuario)
        self.facultad, _ = Facultad.objects.get_or_create(nombre='Facultad PDF')
        self.carrera, _ = Carrera.objects.get_or_create(nombre='Carrera PDF', defaults={'facultad': self.facultad, 'codigo': 'CT-PDF-1'})
        self.est_carr = EstudianteCarrera.objects.create(estudiante=self.estudiante, carrera=self.carrera, estado='Activo')
        self.periodo, _ = PeriodoAcademico.objects.get_or_create(
            nombre='2026-PDF', defaults={'fecha_inicio': date(2026, 1, 1), 'fecha_fin': date(2026, 6, 30), 'fecha_cierre_propuesta': date(2026, 3, 1), 'fecha_cierre_informe': date(2026, 6, 1), 'estado': EstadoPeriodo.CERRADO}
        )
        self.proceso = ProcesoTrabajoSocial.objects.create(estudiante_carrera=self.est_carr, fecha_inicio=timezone.now(), estado='En curso')
        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso, periodo_academico=self.periodo, codigo='PROP-PDF-1', titulo='Propuesta PDF',
            estado=EstadoTramite.APROBADO_EN_UP, entidad='Entidad PDF', poblacion_beneficiada='100', zona='Urbana',
            area='Salud', sector='Público', unidad='Hospital', resena_historica='x', identificacion_necesidad='x',
            justificacion='x', objetivos='x', referente_teorico='x', impacto_social='x', identificacion_poblacion='x', propuesta_social='x'
        )
        self.informe = Informe.objects.create(
            propuesta=self.propuesta, periodo_academico=self.periodo, codigo='INF-PDF-001',
            estado=EstadoTramite.EN_REVISION, version_entrega=1, fecha_envio=timezone.now(),
            # CAMPOS CON CARACTERES ESPECIALES PARA PROBAR EL ESCAPE (Requisito de Jorge)
            resultados='Resultados con <b>negrita</b> y símbolos & especiales.',
            conclusiones='Conclusión válida de más de cincuenta caracteres para cumplir con la regla de negocio.',
            recomendaciones='Recomendación válida de más de cincuenta caracteres para cumplir con la regla de negocio.'
        )

    def test_pdf_se_genera_y_no_esta_vacio(self):
        """El PDF se genera sin errores y tiene un tamaño razonable."""
        pdf_bytes = generar_pdf_informe(self.informe)
        self.assertGreater(len(pdf_bytes), 1000, "El PDF generado es demasiado pequeño o está vacío")

    def test_pdf_contiene_textos_clave(self):
        """pypdf puede extraer los textos principales del informe."""
        pdf_bytes = generar_pdf_informe(self.informe)
        lector = PdfReader(io.BytesIO(pdf_bytes))
        texto = " ".join(p.extract_text() or "" for p in lector.pages)

        self.assertIn("UNIVERSIDAD DE PAMPLONA", texto)
        self.assertIn("INFORME DE TRABAJO SOCIAL", texto)
        self.assertIn("INF-PDF-001", texto)
        self.assertIn("PDF Test", texto)
        self.assertIn("7777777777", texto)

    def test_pdf_no_rompe_con_html_o_ampersand(self):
        """Un campo con <b> o & no rompe el PDF y se escapa correctamente."""
        pdf_bytes = generar_pdf_informe(self.informe)
        lector = PdfReader(io.BytesIO(pdf_bytes))
        texto = " ".join(p.extract_text() or "" for p in lector.pages)

        # Debe aparecer el contenido, pero el escape de _texto_seguro convierte < en &lt;
        self.assertIn("negrita", texto)
        self.assertIn("especiales", texto)
        # Verificamos que el PDF no esté corrupto y tenga páginas
        self.assertGreater(len(lector.pages), 0)

    def test_pdf_con_campos_vacios_no_rompe(self):
        """Si un campo del informe está vacío, el PDF se genera con texto por defecto."""
        # CORREGIDO: Usar '' en lugar de None para evitar NotNullViolation en PostgreSQL
        self.informe.resultados = ''
        self.informe.conclusiones = ''
        self.informe.recomendaciones = ''
        self.informe.save(update_fields=['resultados', 'conclusiones', 'recomendaciones'])

        pdf_bytes = generar_pdf_informe(self.informe)
        lector = PdfReader(io.BytesIO(pdf_bytes))
        texto = " ".join(p.extract_text() or "" for p in lector.pages)

        self.assertIn("Sin resultados registrados", texto)
        self.assertIn("Sin conclusiones registradas", texto)