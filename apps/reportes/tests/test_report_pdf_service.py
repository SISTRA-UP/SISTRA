
from datetime import date
from io import BytesIO

from django.test import SimpleTestCase
from pypdf import PdfReader

from apps.reportes.services.report_pdf_service import (
    generar_pdf_trabajo_social,
)


class ReportePDFTests(SimpleTestCase):

    def datos_base(self, incluir_carrera=False):
        return {
            'incluir_carrera': incluir_carrera,
            'resumen': {
                'total_estudiantes': 2,
                'entidades_publicas': 1,
                'entidades_privadas': 1,
                'total_aprobados': 1,
                'total_rechazados': 1,
            },
            'aprobados': [
                {
                    'nombre': 'Juan Pérez',
                    'titulo': 'Propuesta de trabajo social',
                    'entidad': 'Alcaldía Municipal',
                    'poblacion_beneficiada': 'Adultos mayores',
                    'zona': 'Urbana',
                    'area': 'Social',
                    'sector': 'Público',
                    'unidad': 'Bienestar',
                    'carrera': 'Trabajo Social',
                },
            ],
            'detalle_finales': [
                {
                    'nombre': 'Juan Pérez',
                    'cedula': '123456789',
                    'estado_final': 'Aprobado',
                    'fecha_envio': date(2026, 10, 10),
                    'fecha_decision': date(2026, 10, 15),
                    'tipo_rechazo': '-',
                    'observacion': '-',
                    'carrera': 'Trabajo Social',
                },
                {
                    'nombre': 'María López',
                    'cedula': '987654321',
                    'estado_final': 'Rechazado',
                    'fecha_envio': date(2026, 10, 11),
                    'fecha_decision': date(2026, 10, 16),
                    'tipo_rechazo': 'Documentación incompleta',
                    'observacion': 'Debe corregir los documentos.',
                    'carrera': 'Trabajo Social',
                },
            ],
        }

    def generar_pdf(self, incluir_carrera=False):
        return generar_pdf_trabajo_social(
            self.datos_base(incluir_carrera),
            'Administrador',
            {
                'start': date(2026, 10, 1),
                'end': date(2026, 10, 31),
            },
        )

    def test_genera_pdf_valido(self):
        pdf = self.generar_pdf()

        self.assertTrue(pdf.read().startswith(b'%PDF'))

    def test_pdf_tiene_contenido(self):
        pdf = self.generar_pdf()

        lector = PdfReader(BytesIO(pdf.getvalue()))

        self.assertGreater(len(lector.pages), 0)

    def test_incluye_columna_carrera_para_administrador(self):
        pdf = self.generar_pdf(incluir_carrera=True)

        lector = PdfReader(BytesIO(pdf.getvalue()))
        contenido = ''.join(
            pagina.extract_text() or ''
            for pagina in lector.pages
        )

        self.assertIn('Carrera', contenido)
        self.assertIn('Trabajo Social', contenido)

    def test_no_incluye_columna_carrera_para_director(self):
        pdf = self.generar_pdf(incluir_carrera=False)

        lector = PdfReader(BytesIO(pdf.getvalue()))
        contenido = ''.join(
            pagina.extract_text() or ''
            for pagina in lector.pages
        )

        self.assertNotIn('Carrera', contenido)

    def test_textos_especiales_no_rompen_pdf(self):
        datos = self.datos_base()
        datos['aprobados'][0]['titulo'] = (
            'Atención a niños <menores> & jóvenes'
        )

        pdf = generar_pdf_trabajo_social(
            datos,
            'Administrador',
            {
                'start': date(2026, 10, 1),
                'end': date(2026, 10, 31),
            },
        )

        lector = PdfReader(BytesIO(pdf.getvalue()))

        self.assertGreater(len(lector.pages), 0)
