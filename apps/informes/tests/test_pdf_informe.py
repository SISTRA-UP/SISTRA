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
from apps.usuarios.models import Rol, Usuario
from apps.informes.services.documento_pdf import generar_pdf_informe


class TestGenerarPDFInforme(TestCase):
    """Pruebas estrictas de la función generar_pdf_informe."""

    def setUp(self):
        self.rol, _ = Rol.objects.get_or_create(nombre='Estudiante', defaults={'estado': 'Activo'})
        self.usuario = Usuario.objects.create_user(
            correo_institucional='pdf@unipamplona.edu.co',
            nombre='PDF Test',
            cedula='7777777777',
            nombre_usuario='pdftest',
            password='testpass123',
            rol=self.rol,
            requiere_cambio_contrasena=False,
        )
        self.estudiante = Estudiante.objects.create(usuario=self.usuario)
        self.facultad, _ = Facultad.objects.get_or_create(nombre='Facultad PDF')
        self.carrera, _ = Carrera.objects.get_or_create(
            nombre='Carrera PDF',
            defaults={'facultad': self.facultad, 'codigo': 'CT-PDF-1'}
        )
        self.est_carr = EstudianteCarrera.objects.create(
            estudiante=self.estudiante, carrera=self.carrera, estado='Activo'
        )
        self.periodo, _ = PeriodoAcademico.objects.get_or_create(
            nombre='2026-PDF',
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
            codigo='PROP-PDF-1',
            titulo='Propuesta PDF',
            estado=EstadoTramite.APROBADO_EN_UP,
            entidad='Entidad PDF',
            poblacion_beneficiada='100',
            zona='Urbana',
            area='Salud',
            sector='Público',
            unidad='Hospital',
            resena_historica='x',
            identificacion_necesidad='x',
            justificacion='x',
            objetivos='x',
            referente_teorico='x',
            impacto_social='x',
            identificacion_poblacion='x',
            propuesta_social='x',
        )
        self.informe = Informe.objects.create(
            propuesta=self.propuesta,
            periodo_academico=self.periodo,
            codigo='INF-PDF-001',
            estado=EstadoTramite.EN_REVISION,
            version_entrega=1,
            fecha_envio=timezone.now(),
            resultados='Resultados con <b>negrita</b> y símbolos & especiales.',
            conclusiones='Conclusión válida de más de cincuenta caracteres para cumplir con la regla de negocio.',
            recomendaciones='Recomendación válida de más de cincuenta caracteres para cumplir con la regla de negocio.',
        )

    def test_pdf_se_genera_y_no_esta_vacio(self):
        """El PDF se genera sin errores y tiene un tamaño razonable."""
        pdf_bytes = generar_pdf_informe(self.informe)
        self.assertGreater(len(pdf_bytes), 1000, "El PDF generado es demasiado pequeño o está vacío")
        self.assertIsInstance(pdf_bytes, bytes, "La función debe devolver bytes, no un objeto BytesIO")

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
        self.assertIn("Resultados", texto)
        self.assertIn("Conclusiones", texto)
        self.assertIn("Recomendaciones", texto)

    def test_pdf_no_rompe_con_html_o_ampersand_en_contenido(self):
        """Un campo de contenido con <b> o & no rompe el PDF y se escapa correctamente."""
        pdf_bytes = generar_pdf_informe(self.informe)
        lector = PdfReader(io.BytesIO(pdf_bytes))
        texto = " ".join(p.extract_text() or "" for p in lector.pages)

        # Debe aparecer el contenido legible
        self.assertIn("negrita", texto)
        self.assertIn("especiales", texto)
        
        # Verificamos que el PDF no esté corrupto y tenga páginas
        self.assertGreater(len(lector.pages), 0)

    def test_pdf_no_doble_escape_en_metadatos(self):
        """
        PRUEBA CRÍTICA: Verifica que títulos o entidades con & o <b> 
        no se escapen dos veces (bug reportado en revisión).
        """
        # 1. Modificamos la propuesta para tener caracteres especiales en metadatos
        self.propuesta.titulo = "Salud & Bienestar <b>2026</b>"
        self.propuesta.entidad = "AT&T"
        self.propuesta.save(update_fields=['titulo', 'entidad'])

        # 2. Generamos el PDF
        pdf_bytes = generar_pdf_informe(self.informe)
        lector = PdfReader(io.BytesIO(pdf_bytes))
        texto = " ".join(p.extract_text() or "" for p in lector.pages)

        # 3. Verificamos que el texto se renderice correctamente (legible)
        self.assertIn("Salud & Bienestar", texto)
        self.assertIn("2026", texto)
        self.assertIn("AT&T", texto)
        
        # 4. Verificamos EXPLÍCITAMENTE que NO haya doble escape
        # Si hubiera doble escape, pypdf extraería las entidades HTML literales
        self.assertNotIn("&amp;", texto, "El texto contiene doble escape de ampersand (&amp;)")
        self.assertNotIn("&lt;", texto, "El texto contiene doble escape de menor que (&lt;)")
        self.assertNotIn("&gt;", texto, "El texto contiene doble escape de mayor que (&gt;)")

    def test_pdf_con_campos_vacios_no_rompe(self):
        """Si un campo del informe está vacío, el PDF se genera con texto por defecto."""
        # Usar '' en lugar de None para evitar NotNullViolation en PostgreSQL
        self.informe.resultados = ''
        self.informe.conclusiones = ''
        self.informe.recomendaciones = ''
        self.informe.save(update_fields=['resultados', 'conclusiones', 'recomendaciones'])

        pdf_bytes = generar_pdf_informe(self.informe)
        lector = PdfReader(io.BytesIO(pdf_bytes))
        texto = " ".join(p.extract_text() or "" for p in lector.pages)

        self.assertIn("Sin resultados registrados", texto)
        self.assertIn("Sin conclusiones registradas", texto)
        self.assertIn("Sin recomendaciones registradas", texto)