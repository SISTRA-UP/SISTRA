"""SISTRA-01 · Pruebas de generación del documento PDF de la propuesta.

Verifica:
1. Generación de PDF con una Propuesta real en base de pruebas (código, estudiante,
   carrera, periodo, fechas, los 16 campos del formulario y cronograma de actividades),
   extrayendo los textos con pypdf para comprobar su presencia.
2. Manejo seguro de caracteres especiales XML/HTML (<b>, &, <, >, ", '):
   el PDF se genera sin errores y muestra el texto tal cual (literal).
3. Propuesta sin fechas definidas: se genera correctamente sin lanzar excepciones.
4. Propuesta sin cronograma: se genera correctamente omitiendo la sección de cronograma.
5. Funciones modulares y reutilizables (estilos, encabezado, tabla de campos con
   KeepTogether, construcción del documento con texto de pie configurable) para su
   aprovechamiento en el informe de Trabajo Social (RG-10).
"""

import io
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from pypdf import PdfReader
from reportlab.platypus import KeepTogether

from apps.parametrizacion.models import (
    Carrera,
    EstadoPeriodo,
    Facultad,
    PeriodoAcademico,
)
from apps.personas.models import (
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.models import ActividadCronograma, Propuesta, SectorEntidad
from apps.propuestas.services.documento_pdf import (
    _formatear_fecha,
    _texto_seguro,
    construir_documento_pdf,
    construir_encabezado_pdf,
    construir_tabla_campos,
    construir_tabla_cronograma,
    generar_pdf_propuesta,
    obtener_estilos_pdf,
)
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()


class GenerarPdfPropuestaModeloRealTests(TestCase):
    """Pruebas de integración de generar_pdf_propuesta con Propuesta real en BD."""

    @classmethod
    def setUpTestData(cls):
        hoy = timezone.localdate()
        cls.rol_estudiante, _ = Rol.objects.get_or_create(nombre="Estudiante")
        cls.facultad = Facultad.objects.create(
            nombre="Facultad de Ingenierías y Arquitectura",
            estado=Estado.ACTIVO,
        )
        cls.carrera = Carrera.objects.create(
            facultad=cls.facultad,
            nombre="Ingeniería de Sistemas",
            codigo="SIS-PDF-01",
            estado=Estado.ACTIVO,
        )
        cls.periodo = PeriodoAcademico.objects.create(
            nombre="2026-1",
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin=hoy + timedelta(days=120),
            fecha_cierre_propuesta=hoy + timedelta(days=40),
            fecha_cierre_informe=hoy + timedelta(days=100),
            estado=EstadoPeriodo.VIGENTE,
        )
        cls.usuario = Usuario.objects.create_user(
            correo_institucional="laura.pdf@unipamplona.edu.co",
            password="Password123!",
            nombre="Laura Marcela Pérez Gómez",
            cedula="1098777001",
            nombre_usuario="laura.pdf",
            rol=cls.rol_estudiante,
            requiere_cambio_contrasena=False,
        )
        cls.estudiante = Estudiante.objects.create(usuario=cls.usuario)
        cls.inscripcion = EstudianteCarrera.objects.create(
            estudiante=cls.estudiante,
            carrera=cls.carrera,
            fecha_registro=hoy - timedelta(days=20),
            estado=EstadoInscripcion.ACTIVO,
        )
        cls.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=cls.inscripcion,
            fecha_inicio=timezone.now() - timedelta(days=15),
            estado=EstadoAvance.EN_CURSO,
        )

    def _crear_propuesta_completa(self, codigo: str = "PROP-2026-001") -> Propuesta:
        return Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo=codigo,
            fecha_inicio=date(2026, 1, 15),
            fecha_fin=date(2026, 6, 30),
            titulo="Capacitación Digital Comunitaria",
            entidad="Fundación Esperanza Viva",
            sector_entidad=SectorEntidad.PRIVADO,
            poblacion_beneficiada="120 familias de la zona",
            identificacion_poblacion="Madres cabeza de hogar y jóvenes",
            resena_historica="Organización fundada en 2010 dedicada al desarrollo social",
            identificacion_necesidad="Brecha digital y falta de acceso a herramientas informáticas",
            justificacion="La formación tecnológica mejora la empleabilidad comunitaria",
            objetivos="Capacitar a 120 personas en habilidades digitales básicas",
            referente_teorico="Teoría del empoderamiento comunitario y alfabetización digital",
            propuesta_social="Talleres prácticos semanales con módulos modulares",
            impacto_social="Incremento en un 40% en inserción laboral de participantes",
            zona="Urbana",
            area="Desarrollo Social y Comunitario",
            sector="Tecnología Educativa",
            unidad="Barrio San Martín",
        )

    def test_generar_pdf_propuesta_completa_con_cronograma(self):
        """Verifica que se genera el PDF de una Propuesta real completa y pypdf extrae sus textos."""
        propuesta = self._crear_propuesta_completa()
        ActividadCronograma.objects.create(
            propuesta=propuesta,
            orden=1,
            nombre="Diagnóstico y convocatoria",
            descripcion="Inscripción de beneficiarios y prueba diagnóstica",
            fecha_inicio=date(2026, 2, 1),
            fecha_fin=date(2026, 2, 28),
            responsable="Laura Pérez",
        )
        ActividadCronograma.objects.create(
            propuesta=propuesta,
            orden=2,
            nombre="Ejecución de talleres",
            descripcion="Módulos de herramientas ofimáticas",
            fecha_inicio=date(2026, 3, 1),
            fecha_fin=date(2026, 5, 31),
            responsable="Equipo facilitador",
        )

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        self.assertGreater(len(reader.pages), 0)
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)
        texto_normalizado = " ".join(texto_completo.split())

        # Metadatos y pie de página
        self.assertIn("PROP-2026-001", texto_completo)
        self.assertIn("Laura Marcela Pérez Gómez", texto_completo)
        self.assertIn("Ingeniería de Sistemas", texto_completo)
        self.assertIn("2026-1", texto_completo)
        self.assertIn("Fecha estimada de inicio:", texto_normalizado)
        self.assertIn("Fecha estimada de finalización:", texto_normalizado)
        self.assertIn("15/01/2026", texto_completo)
        self.assertIn("30/06/2026", texto_completo)
        self.assertIn("Propuesta de Trabajo Social", texto_completo)

        # 16 campos del formulario
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

        # Cronograma de actividades
        self.assertIn("CRONOGRAMA DE ACTIVIDADES", texto_completo)
        self.assertIn("Diagnóstico y convocatoria", texto_completo)
        self.assertIn("Ejecución de talleres", texto_completo)
        self.assertIn("Laura Pérez", texto_completo)

    def test_generar_pdf_propuesta_caracteres_especiales_html_y_ampersand(self):
        """Verifica que un campo con <b> o & no rompe ReportLab y muestra el texto tal cual."""
        propuesta = self._crear_propuesta_completa(codigo="PROP-2026-002")
        propuesta.titulo = "Investigación sobre <b>impacto social</b> & desarrollo comunitario"
        propuesta.justificacion = "Sección de CyT & Innovación: <Prueba de escape>"
        propuesta.save(update_fields=["titulo", "justificacion"])

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)

        self.assertIn("<b>impacto social</b>", texto_completo)
        self.assertIn("&", texto_completo)
        self.assertIn("<Prueba de escape>", texto_completo)

    def test_generar_pdf_propuesta_sin_fechas_no_falla(self):
        """Una propuesta sin fechas (fechas en None) no debe fallar y debe generar un PDF válido."""
        propuesta = self._crear_propuesta_completa(codigo="PROP-2026-003")
        propuesta.fecha_inicio = None
        propuesta.fecha_fin = None
        propuesta.save(update_fields=["fecha_inicio", "fecha_fin"])

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)
        self.assertIn("No definida", texto_completo)

    def test_generar_pdf_propuesta_sin_cronograma(self):
        """Una propuesta sin cronograma se genera correctamente omitiendo la sección."""
        propuesta = self._crear_propuesta_completa(codigo="PROP-2026-004")

        pdf_bytes = generar_pdf_propuesta(propuesta)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)
        self.assertNotIn("CRONOGRAMA DE ACTIVIDADES", texto_completo)

    def test_generar_pdf_propuesta_con_campo_muy_largo(self):
        """Un campo de varias páginas no rompe el PDF y sale completo."""
        propuesta = self._crear_propuesta_completa(codigo="PROP-2026-005")
        propuesta.justificacion = "Justificación larga del proyecto social. " * 600 + "FIN-DE-LA-JUSTIFICACION"
        propuesta.save(update_fields=["justificacion"])

        pdf_bytes = generar_pdf_propuesta(propuesta)

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)
        self.assertGreater(len(reader.pages), 2)
        self.assertIn("FIN-DE-LA-JUSTIFICACION", texto_completo)


class ComponentesComunesPdfTests(SimpleTestCase):
    """Pruebas unitarias para los componentes reutilizables de documento_pdf."""

    def test_partes_comunes_reutilizables_para_informe(self):
        """Verifica que las funciones modulares comunes se puedan invocar independientemente."""
        estilos = obtener_estilos_pdf()
        self.assertIn("Titulo", estilos)
        self.assertIn("CampoTitulo", estilos)
        self.assertIn("CampoContenido", estilos)

        historia = construir_encabezado_pdf(
            titulo="INFORME DE TRABAJO SOCIAL",
            subtitulo="RG-10 · Informe final",
            metadatos=[("Código", "INF-001"), ("Estudiante", "Carlos Ruiz")],
            estilos=estilos,
        )
        self.assertGreater(len(historia), 0)

        campos_informe = [
            ("Resultados", "Se cumplieron los objetivos al 100%"),
            ("Conclusiones", "Conclusión exitosa"),
            ("Recomendaciones", "Continuar el programa"),
        ]
        tabla_campos = construir_tabla_campos(campos_informe, estilos=estilos)
        self.assertEqual(len(tabla_campos), 3)
        self.assertTrue(all(isinstance(item, KeepTogether) for item in tabla_campos))
        historia.extend(tabla_campos)

        crono_vacio = construir_tabla_cronograma([], estilos=estilos)
        self.assertEqual(crono_vacio, [])

        pie_informe = "SISTRA · Universidad de Pamplona — Informe de Trabajo Social"
        pdf_bytes = construir_documento_pdf(historia, pie_texto=pie_informe)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        reader = PdfReader(io.BytesIO(pdf_bytes))
        texto_completo = "".join(pagina.extract_text() or "" for pagina in reader.pages)
        self.assertIn("INFORME DE TRABAJO SOCIAL", texto_completo)
        self.assertIn("Informe de Trabajo Social", texto_completo)
        self.assertIn("Página 1 de 1", texto_completo)

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
