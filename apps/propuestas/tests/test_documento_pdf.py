"""SISTRA-01 · Pruebas unitarias para la generación del documento PDF de la propuesta.

Verifica:
1. Generación de PDF con propuesta completa (código, estudiante, carrera, periodo,
   fechas y los 16 campos del formulario) y cronograma de actividades, extrayendo
   los textos con pypdf para comprobar su presencia.
2. Manejo seguro de caracteres especiales XML/HTML (<b>, &, <, >, ", '):
   el PDF se genera sin errores y muestra el texto tal cual (literal).
3. Propuesta sin fechas definidas: se genera correctamente sin lanzar excepciones.
4. Propuesta sin cronograma: se genera correctamente omitiendo la sección de cronograma.
5. Funciones modulares y reutilizables (estilos, encabezado, tabla de campos) para
   su aprovechamiento en informe de Trabajo Social (RG-10).
"""

import io
from datetime import date
from unittest.mock import MagicMock

from django.test import SimpleTestCase
from pypdf import PdfReader

from apps.propuestas.models import SectorEntidad
from apps.propuestas.services.documento_pdf import (
    CAMPOS_FORMULARIO_PROPUESTA,
    _formatear_fecha,
    _texto_seguro,
    construir_encabezado_pdf,
    construir_tabla_campos,
    construir_tabla_cronograma,
    generar_pdf_propuesta,
    obtener_estilos_pdf,
)


class GenerarPdfPropuestaTests(SimpleTestCase):
    """Pruebas para generar_pdf_propuesta y sus componentes auxiliares."""

    def _crear_propuesta_mock_completa(self):
        """Crea un objeto mock de propuesta con todos los atributos y relaciones."""
        propuesta = MagicMock()
        propuesta.codigo = "PROP-2026-001"
        propuesta.fecha_inicio = date(2026, 2, 1)
        propuesta.fecha_fin = date(2026, 6, 30)

        # 16 campos del formulario oficial
        propuesta.titulo = "Capacitación Digital Comunitaria"
        propuesta.entidad = "Fundación Esperanza Viva"
        propuesta.sector_entidad = SectorEntidad.PRIVADO
        propuesta.poblacion_beneficiada = "120 familias de la zona"
        propuesta.identificacion_poblacion = "Madres cabeza de hogar y jóvenes"
        propuesta.resena_historica = "Organización fundada en 2010 dedicada al desarrollo social"
        propuesta.identificacion_necesidad = "Brecha digital y falta de acceso a herramientas informáticas"
        propuesta.justificacion = "La formación tecnológica mejora la empleabilidad comunitaria"
        propuesta.objetivos = "Capacitar a 120 personas en habilidades digitales básicas"
        propuesta.referente_teorico = "Teoría del empoderamiento comunitario y alfabetización digital"
        propuesta.propuesta_social = "Talleres prácticos semanales con módulos modulares"
        propuesta.impacto_social = "Incremento en un 40% en inserción laboral de participantes"
        propuesta.zona = "Urbana"
        propuesta.area = "Desarrollo Social y Comunitario"
        propuesta.sector = "Tecnología Educativa"
        propuesta.unidad = "Barrio San Martín"

        # Relación con Estudiante, Carrera y Periodo
        estudiante = MagicMock()
        estudiante.usuario.nombre = "Laura Marcela Pérez Gómez"
        carrera = MagicMock()
        carrera.nombre = "Ingeniería de Sistemas"
        estudiante_carrera = MagicMock()
        estudiante_carrera.estudiante = estudiante
        estudiante_carrera.carrera = carrera

        proceso = MagicMock()
        proceso.estudiante_carrera = estudiante_carrera
        propuesta.proceso = proceso

        periodo = MagicMock()
        periodo.nombre = "2026-1"
        propuesta.periodo_academico = periodo

        # Cronograma con 2 actividades
        act1 = MagicMock()
        act1.orden = 1
        act1.nombre = "Diagnóstico y convocatoria"
        act1.descripcion = "Inscripción de beneficiarios y prueba diagnóstica"
        act1.fecha_inicio = date(2026, 2, 1)
        act1.fecha_fin = date(2026, 2, 28)
        act1.responsable = "Laura Pérez"

        act2 = MagicMock()
        act2.orden = 2
        act2.nombre = "Ejecución de talleres"
        act2.descripcion = "Módulos de herramientas ofimáticas"
        act2.fecha_inicio = date(2026, 3, 1)
        act2.fecha_fin = date(2026, 5, 31)
        act2.responsable = "Equipo facilitador"

        propuesta.cronograma.all.return_value.order_by.return_value = [act1, act2]

        return propuesta

    def test_generar_pdf_propuesta_completa_con_cronograma(self):
        """Verifica que se genera el PDF de una propuesta completa y que pypdf extrae sus textos."""
        propuesta = self._crear_propuesta_mock_completa()

        pdf_bytes = generar_pdf_propuesta(propuesta)

        # 1. Validar que retorna bytes de PDF
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        # 2. Extraer texto usando pypdf
        reader = PdfReader(io.BytesIO(pdf_bytes))
        self.assertGreater(len(reader.pages), 0)
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)

        # 3. Comprobar que los metadatos aparecen en el texto
        self.assertIn("PROP-2026-001", texto_completo)
        self.assertIn("Laura Marcela Pérez Gómez", texto_completo)
        self.assertIn("Ingeniería de Sistemas", texto_completo)
        self.assertIn("2026-1", texto_completo)
        self.assertIn("01/02/2026", texto_completo)
        self.assertIn("30/06/2026", texto_completo)

        # 4. Comprobar que los 16 campos aparecen en el texto
        self.assertIn("Capacitación Digital Comunitaria", texto_completo)
        self.assertIn("Fundación Esperanza Viva", texto_completo)
        self.assertIn("Privado", texto_completo)
        self.assertIn("120 familias de la zona", texto_completo)
        self.assertIn("Madres cabeza de hogar y jóvenes", texto_completo)
        self.assertIn("Organización fundada en 2010 dedicada al desarrollo social", texto_completo)
        self.assertIn("Brecha digital y falta de acceso a herramientas informáticas", texto_completo)
        self.assertIn("La formación tecnológica mejora la empleabilidad comunitaria", texto_completo)
        self.assertIn("Capacitar a 120 personas en habilidades digitales básicas", texto_completo)
        self.assertIn("Teoría del empoderamiento comunitario y alfabetización digital", texto_completo)
        self.assertIn("Talleres prácticos semanales con módulos modulares", texto_completo)
        self.assertIn("Incremento en un 40% en inserción laboral de participantes", texto_completo)
        self.assertIn("Urbana", texto_completo)
        self.assertIn("Desarrollo Social y Comunitario", texto_completo)
        self.assertIn("Tecnología Educativa", texto_completo)
        self.assertIn("Barrio San Martín", texto_completo)

        # 5. Comprobar que las actividades del cronograma aparecen
        self.assertIn("CRONOGRAMA DE ACTIVIDADES", texto_completo)
        self.assertIn("Diagnóstico y convocatoria", texto_completo)
        self.assertIn("Ejecución de talleres", texto_completo)
        self.assertIn("Laura Pérez", texto_completo)

    def test_generar_pdf_propuesta_caracteres_especiales_html_y_ampersand(self):
        """Verifica que un campo con <b> o & no rompe ReportLab y muestra el texto tal cual."""
        propuesta = self._crear_propuesta_mock_completa()

        # Insertar etiquetas HTML y caracteres especiales en varios campos
        texto_con_etiquetas = "Investigación sobre <b>impacto social</b> & desarrollo comunitario"
        texto_con_ampersand = "Sección de CyT & Innovación: <Prueba de escape>"

        propuesta.titulo = texto_con_etiquetas
        propuesta.justificacion = texto_con_ampersand
        propuesta.cronograma = None  # Sin cronograma en este caso

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)

        # Debe mostrarse el texto literal con las etiquetas y el ampersand
        self.assertIn("<b>impacto social</b>", texto_completo)
        self.assertIn("&", texto_completo)
        self.assertIn("<Prueba de escape>", texto_completo)

    def test_generar_pdf_propuesta_sin_fechas_no_falla(self):
        """Una propuesta sin fechas (fechas en None) no debe fallar y debe generar un PDF válido."""
        propuesta = self._crear_propuesta_mock_completa()
        propuesta.fecha_inicio = None
        propuesta.fecha_fin = None

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)

        # Debe contener el texto alternativo para fechas ausentes
        self.assertIn("No definida", texto_completo)

    def test_generar_pdf_propuesta_sin_cronograma(self):
        """Una propuesta sin cronograma se genera correctamente omitiendo la sección."""
        propuesta = self._crear_propuesta_mock_completa()
        propuesta.cronograma.all.return_value.order_by.return_value = []

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)

        # No debe aparecer el encabezado de cronograma si no hay actividades
        self.assertNotIn("CRONOGRAMA DE ACTIVIDADES", texto_completo)

    def test_partes_comunes_reutilizables_para_informe(self):
        """Verifica que las funciones modulares comunes se puedan invocar independientemente."""
        estilos = obtener_estilos_pdf()
        self.assertIn("Titulo", estilos)
        self.assertIn("CampoTitulo", estilos)
        self.assertIn("CampoContenido", estilos)

        encabezado = construir_encabezado_pdf(
            titulo="INFORME DE TRABAJO SOCIAL",
            subtitulo="RG-10 · Informe final",
            metadatos=[("Código", "INF-001"), ("Estudiante", "Carlos Ruiz")],
            estilos=estilos,
        )
        self.assertGreater(len(encabezado), 0)

        campos_informe = [
            ("Resultados", "Se cumplieron los objetivos al 100%"),
            ("Conclusiones", "Conclusión exitosa"),
            ("Recomendaciones", "Continuar el programa"),
        ]
        tabla_campos = construir_tabla_campos(campos_informe, estilos=estilos)
        self.assertGreater(len(tabla_campos), 0)

        crono_vacio = construir_tabla_cronograma([], estilos=estilos)
        self.assertEqual(crono_vacio, [])

    def test_texto_seguro_helper(self):
        """Verifica la función interna de escape seguro de textos."""
        self.assertEqual(_texto_seguro(None), "")
        self.assertEqual(_texto_seguro("Normal"), "Normal")
        self.assertEqual(_texto_seguro("A & B"), "A &amp; B")
        self.assertEqual(_texto_seguro("<b>bold</b>"), "&lt;b&gt;bold&lt;/b&gt;")
        self.assertEqual(_texto_seguro('Quote "test"'), "Quote &quot;test&quot;")
        self.assertEqual(_texto_seguro("Línea 1\nLínea 2"), "Línea 1<br/>Línea 2")

    def test_formatear_fecha_helper(self):
        """Verifica la función interna de formateo de fechas."""
        self.assertEqual(_formatear_fecha(None), "No definida")
        self.assertEqual(_formatear_fecha(date(2026, 5, 15)), "15/05/2026")
        self.assertEqual(_formatear_fecha("15/05/2026"), "15/05/2026")
