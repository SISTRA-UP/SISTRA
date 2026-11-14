"""SISTRA-01 · Montaje de propuesta – Trabajo Social: pruebas unitarias.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test apps.propuestas.tests.test_montaje
"""
import io
import zipfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
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
    MSG_01_03,
    MSG_01_04,
    MSG_01_05,
    CargaPlantillaWordForm,
    PropuestaMontajeForm,
)
from apps.propuestas.models import EstadoTramite, Propuesta, SectorEntidad
from apps.propuestas.services.montaje import PlantillaInvalidaError, extraer_datos_plantilla
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _docx_con_etiquetas(etiquetas: dict[str, str]) -> bytes:
    """Genera un .docx mínimo en memoria con los pares etiqueta: valor."""
    parrafos = ''.join(
        f'<w:p><w:r><w:t>{etiqueta}: {valor}</w:t></w:r></w:p>'
        for etiqueta, valor in etiquetas.items()
    )
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>'
        + parrafos +
        '</w:body>'
        '</w:document>'
    ).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('word/document.xml', xml_content)
    return buf.getvalue()


# Todas las etiquetas obligatorias de la plantilla oficial
ETIQUETAS_COMPLETAS = {
    'Título de la propuesta': 'Proyecto de prueba',
    'Entidad': 'Fundación Test',
    'Sector de la entidad': 'Público',
    'Población beneficiada': '100 personas',
    'Identificación de la población': 'Jóvenes rurales',
    'Reseña histórica': 'Historia institucional',
    'Identificación de la necesidad': 'Necesidad identificada',
    'Justificación': 'Justificación del proyecto',
    'Objetivos': 'Objetivo general',
    'Referente teórico': 'Marco teórico',
    'Propuesta social': 'Metodología de trabajo',
    'Impacto social': 'Impacto esperado',
    'Zona': 'Rural',
    'Área': 'Educación',
    'Sector': 'Social',
    'Unidad': 'Vereda El Porvenir',
}

DATOS_COMPLETOS_ENVIO = {
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
    'objetivos': 'Capacitar a 80 personas en el uso de plataformas web.',
    'referente_teorico': 'Teoría de adopción tecnológica comunitaria.',
    'propuesta_social': 'Talleres prácticos semanales de 4 horas.',
    'impacto_social': 'Inserción productiva y cierre de brecha digital local.',
}


# ---------------------------------------------------------------------------
# Clase base
# ---------------------------------------------------------------------------

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

        # Periodo académico vigente
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
            requiere_cambio_contrasena=False,
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
            requiere_cambio_contrasena=False,
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


# ---------------------------------------------------------------------------
# Pruebas de vistas y flujos
# ---------------------------------------------------------------------------

class TestMontajeVistasYFlujos(BaseMontajeTestCase):
    """Pruebas de endpoints GET y POST para el montaje de la propuesta."""

    def test_acceso_requiere_login(self):
        """Usuarios no autenticados son redirigidos al login."""
        url = reverse('propuestas:montaje')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_director_recibe_403(self):
        """Un Director que abre /propuestas/mi-propuesta/ recibe 403, no 500."""
        self.client.force_login(self.user_director)
        url = reverse('propuestas:montaje')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_get_muestra_formulario_inicial_vacio(self):
        """Un estudiante sin propuesta ve el formulario de nueva propuesta."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Propuesta de Trabajo Social')
        self.assertContains(resp, 'Nueva Propuesta')

    def test_guardar_borrador_parcial_y_auditoria(self):
        """Un estudiante puede guardar un borrador con campos incompletos y queda registro en Auditoría."""
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

        # Auditoría de creación
        auditoria = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            tabla_afectada='propuesta',
            accion='Crear propuesta',
            resultado='Éxito',
        ).first()
        self.assertIsNotNone(auditoria)

    def test_guardar_borrador_existente_genera_auditoria_guardar(self):
        """Al guardar un borrador ya existente se registra 'Guardar borrador'."""
        hoy = timezone.localdate()
        propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo='PROP-TEST-GUARD',
            titulo='Borrador inicial',
            estado=EstadoTramite.BORRADOR,
            fecha_inicio=hoy,
            fecha_fin=hoy + timedelta(days=30),
        )
        self.client.force_login(self.user_estudiante)
        self.client.post(reverse('propuestas:montaje'), {
            'accion': 'guardar',
            'titulo': 'Borrador actualizado',
        })
        auditoria = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            accion='Guardar borrador',
            resultado='Éxito',
        ).first()
        self.assertIsNotNone(auditoria)

    def test_enviar_incompleto_falla_validacion(self):
        """No se permite enviar la propuesta si no está al 100% de obligatorios."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        data = {
            'accion': 'enviar',
            'titulo': 'Proyecto Incompleto',
        }
        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Para enviar la propuesta a revisión se deben completar todos los campos')

        prop = Propuesta.objects.filter(proceso=self.proceso).first()
        if prop:
            self.assertNotEqual(prop.estado, EstadoTramite.EN_REVISION)

    def test_enviar_completo_exitoso_y_notifica_y_auditoria(self):
        """Al completar todos los campos, el envío pasa a EN_REVISION, notifica y audita."""
        self.client.force_login(self.user_estudiante)
        url = reverse('propuestas:montaje')
        hoy = timezone.localdate()

        data = {
            **DATOS_COMPLETOS_ENVIO,
            'fecha_inicio': str(hoy),
            'fecha_fin': str(hoy + timedelta(days=90)),
        }

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        propuesta = Propuesta.objects.get(proceso=self.proceso)
        self.assertEqual(propuesta.estado, EstadoTramite.EN_REVISION)
        self.assertIsNotNone(propuesta.fecha_envio)

        # Historial
        historial = HistorialEstado.objects.filter(propuesta=propuesta).latest('fecha_hora')
        self.assertEqual(historial.estado_nuevo, EstadoTramite.EN_REVISION)

        # Notificación al director
        notif = Notificacion.objects.filter(usuario=self.user_director, propuesta=propuesta).first()
        self.assertIsNotNone(notif)
        self.assertIn('Capacitación Digital', notif.mensaje)

        # Auditoría de envío
        audit = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            accion='Enviar propuesta',
            resultado='Éxito',
        ).first()
        self.assertIsNotNone(audit)

    def test_propuesta_en_revision_queda_bloqueada_y_auditoria_bloqueado(self):
        """La edición de una propuesta En revisión queda en Bloqueado en auditoría."""
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

        # POST que debe ser rechazado
        self.client.post(url, {'accion': 'guardar', 'titulo': 'Cambio no permitido'})
        propuesta.refresh_from_db()
        self.assertEqual(propuesta.titulo, 'Propuesta Bloqueada')

        audit = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            accion='Editar propuesta',
            resultado='Bloqueado',
        ).first()
        self.assertIsNotNone(audit)

    def test_sin_periodo_vigente_no_crea_propuesta(self):
        """Si no hay periodo vigente, la propuesta no se crea y se muestra aviso."""
        self.periodo.estado = EstadoPeriodo.CERRADO
        self.periodo.save()

        self.client.force_login(self.user_estudiante)
        resp = self.client.post(reverse('propuestas:montaje'), {
            'accion': 'guardar',
            'titulo': 'Propuesta sin periodo',
        })
        # Debe renderizar el formulario con el mensaje (no redirigir)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No hay un periodo académico vigente')
        self.assertEqual(Propuesta.objects.filter(proceso=self.proceso).count(), 0)

    def test_crear_propuesta_asigna_version_plantilla(self):
        """Al crear una propuesta nueva se asigna la versión de plantilla vigente si existe."""
        from apps.parametrizacion.models import Plantilla, VersionPlantilla
        hoy = timezone.localdate()
        plantilla = Plantilla.objects.create(
            nombre='Plantilla Propuesta',
            tipo='propuesta',
            estado='Activo',
        )
        version = VersionPlantilla.objects.create(
            plantilla=plantilla,
            usuario=self.user_director,
            numero_version=1,
            nombre_archivo='propuesta_v1.docx',
            ruta_archivo='propuestas/propuesta_v1.docx',
            es_vigente=True,
        )

        self.client.force_login(self.user_estudiante)
        self.client.post(reverse('propuestas:montaje'), {
            'accion': 'guardar',
            'titulo': 'Propuesta con versión',
        })
        propuesta = Propuesta.objects.filter(proceso=self.proceso).first()
        self.assertIsNotNone(propuesta)
        self.assertEqual(propuesta.version_plantilla, version)

    def test_carga_word_corrupto_rechaza_sin_error_500_y_audita_fallo(self):
        """Un Word con contenido corrupto se rechaza con MSG-01-03 sin error 500 y se audita Fallo."""
        self.client.force_login(self.user_estudiante)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('word/document.xml', b'<w:document><w:body><unclosed_tag')
        buf.seek(0)
        archivo = SimpleUploadedFile('corrupto.docx', buf.getvalue())

        resp = self.client.post(
            reverse('propuestas:montaje'),
            {'accion': 'importar_word', 'archivo': archivo},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, MSG_01_03)

        auditoria = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            accion='Cargar plantilla',
            resultado='Fallo',
        ).first()
        self.assertIsNotNone(auditoria)

    def test_carga_word_muestra_etiquetas_faltantes(self):
        """Al subir una plantilla a la que le faltan etiquetas, la pantalla muestra MSG-01-03 y nombra las faltantes."""
        self.client.force_login(self.user_estudiante)
        etiquetas_parciales = {
            'Título de la propuesta': 'Proyecto Parcial',
            'Entidad': 'Entidad Parcial',
        }
        contenido = _docx_con_etiquetas(etiquetas_parciales)
        archivo = SimpleUploadedFile('incompleto.docx', contenido)

        resp = self.client.post(
            reverse('propuestas:montaje'),
            {'accion': 'importar_word', 'archivo': archivo},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, MSG_01_03)
        self.assertContains(resp, 'Etiquetas no encontradas')

        auditoria = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            accion='Cargar plantilla',
            resultado='Fallo',
        ).latest('fecha_hora')
        self.assertIsNotNone(auditoria)
        self.assertIn('Faltan etiquetas', auditoria.detalle)

    def test_subir_archivo_no_docx_registra_auditoria_fallo(self):
        """Al subir un archivo que no es .docx queda en auditoría Cargar plantilla / Fallo."""
        self.client.force_login(self.user_estudiante)
        archivo = SimpleUploadedFile('documento.pdf', b'contenido pdf no docx')

        resp = self.client.post(
            reverse('propuestas:montaje'),
            {'accion': 'importar_word', 'archivo': archivo},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, MSG_01_04)

        auditoria = Auditoria.objects.filter(
            usuario=self.user_estudiante,
            accion='Cargar plantilla',
            resultado='Fallo',
        ).latest('fecha_hora')
        self.assertIsNotNone(auditoria)
        self.assertIn(MSG_01_04, auditoria.detalle)

    def test_enviar_incompleto_muestra_msg_05_en_campos_obligatorios(self):
        """Al intentar enviar con campos obligatorios vacíos se muestra MSG-01-05 en cada campo."""
        self.client.force_login(self.user_estudiante)
        resp = self.client.post(reverse('propuestas:montaje'), {
            'accion': 'enviar',
            'titulo': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, MSG_01_05)


# ---------------------------------------------------------------------------
# Pruebas del servicio de plantilla Word
# ---------------------------------------------------------------------------

class TestServicioPlantillaWord(TestCase):
    """Pruebas del parser de plantilla Word (.docx)."""

    def test_validador_rechaza_archivos_no_docx(self):
        """El formulario rechaza archivos que no sean .docx (MSG-01-04)."""
        archivo = SimpleUploadedFile('documento.pdf', b'contenido')
        form = CargaPlantillaWordForm(data={}, files={'archivo': archivo})
        self.assertFalse(form.is_valid())
        from apps.propuestas.forms.montaje import MSG_01_04
        self.assertIn(MSG_01_04, form.errors['archivo'])

    def test_word_sin_plantilla_sistra_se_rechaza_con_msg_03(self):
        """Un Word que no es la plantilla de SISTRA se rechaza con MSG-01-03."""
        # Documento con párrafos que no coinciden con ninguna etiqueta oficial
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Problema: descripción del problema</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Actividades: lista de actividades</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>'
        ).encode('utf-8')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('word/document.xml', xml_content)
        buf.seek(0)

        with self.assertRaises(PlantillaInvalidaError):
            extraer_datos_plantilla(buf)

    def test_word_con_todas_las_etiquetas_llena_campos(self):
        """Un Word con todas las etiquetas de SISTRA completa los campos correctamente."""
        contenido = _docx_con_etiquetas(ETIQUETAS_COMPLETAS)
        buf = io.BytesIO(contenido)
        datos, avisos = extraer_datos_plantilla(buf)

        self.assertEqual(datos.get('titulo'), 'Proyecto de prueba')
        self.assertEqual(datos.get('entidad'), 'Fundación Test')
        self.assertEqual(datos.get('sector_entidad'), SectorEntidad.PUBLICO)
        self.assertEqual(datos.get('zona'), 'Rural')
        self.assertEqual(datos.get('area'), 'Educación')
        self.assertEqual(datos.get('sector'), 'Social')
        self.assertEqual(datos.get('unidad'), 'Vereda El Porvenir')
        self.assertEqual(avisos, [])

    def test_sector_invalido_deja_vacio_y_avisa(self):
        """Si el sector de la entidad no es Público ni Privado, se deja vacío y se avisa."""
        etiquetas = {**ETIQUETAS_COMPLETAS, 'Sector de la entidad': 'Mixto'}
        contenido = _docx_con_etiquetas(etiquetas)
        datos, avisos = extraer_datos_plantilla(io.BytesIO(contenido))
        self.assertNotIn('sector_entidad', datos)
        self.assertTrue(any('Sector de la entidad' in av for av in avisos))

    def test_extraccion_desde_docx_xml_valido(self):
        """Genera un .docx mínimo con zipfile y valida extracción de campos presentes."""
        # Solo un subconjunto de etiquetas → debe fallar la validación de plantilla
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Título de la propuesta: Alfabetización Digital Rural</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Entidad: Asociación Progresar</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Justificación: Necesidad sentida de la comunidad</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>'
        ).encode('utf-8')

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('word/document.xml', xml_content)
        buf.seek(0)

        # Falta la mayoría de etiquetas → PlantillaInvalidaError
        with self.assertRaises(PlantillaInvalidaError) as ctx:
            extraer_datos_plantilla(buf)
        self.assertIn('Etiquetas no encontradas', str(ctx.exception))

    def test_sector_publico_sin_tilde_o_mayusculas_normaliza_a_valor_oficial(self):
        """«publico» o «PÚBLICO» en la plantilla queda como el valor oficial «Público»."""
        # 1. minúsculas sin tilde
        etiquetas_min = {**ETIQUETAS_COMPLETAS, 'Sector de la entidad': 'publico'}
        datos_min, avisos_min = extraer_datos_plantilla(io.BytesIO(_docx_con_etiquetas(etiquetas_min)))
        self.assertEqual(datos_min.get('sector_entidad'), SectorEntidad.PUBLICO)
        self.assertEqual(datos_min.get('sector_entidad'), 'Público')
        self.assertEqual(avisos_min, [])

        # 2. mayúsculas con tilde
        etiquetas_may = {**ETIQUETAS_COMPLETAS, 'Sector de la entidad': 'PÚBLICO'}
        datos_may, avisos_may = extraer_datos_plantilla(io.BytesIO(_docx_con_etiquetas(etiquetas_may)))
        self.assertEqual(datos_may.get('sector_entidad'), SectorEntidad.PUBLICO)
        self.assertEqual(datos_may.get('sector_entidad'), 'Público')
        self.assertEqual(avisos_may, [])

        # 3. mayúsculas privado
        etiquetas_priv = {**ETIQUETAS_COMPLETAS, 'Sector de la entidad': 'PRIVADO'}
        datos_priv, avisos_priv = extraer_datos_plantilla(io.BytesIO(_docx_con_etiquetas(etiquetas_priv)))
        self.assertEqual(datos_priv.get('sector_entidad'), SectorEntidad.PRIVADO)
        self.assertEqual(datos_priv.get('sector_entidad'), 'Privado')
        self.assertEqual(avisos_priv, [])

    def test_word_contenido_corrupto_lanza_plantilla_invalida_error(self):
        """Un Word con document.xml corrupto lanza PlantillaInvalidaError (no ParseError)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('word/document.xml', b'<w:document><w:body><unclosed')
        buf.seek(0)

        with self.assertRaises(PlantillaInvalidaError):
            extraer_datos_plantilla(buf)
