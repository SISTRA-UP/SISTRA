"""SISTRA-11 · Parametrización: pruebas de documentos y formatos.

Se ejecutan con:
    python manage.py test apps.parametrizacion.tests.test_documentos
"""
import io
import os

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Plantilla, VersionPlantilla
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso, Usuario


def _crear_admin():
    rol, _ = Rol.objects.get_or_create(nombre='Administrador', defaults={'estado': Estado.ACTIVO})
    usuario = Usuario.objects.create_user(
        correo_institucional='admin@unipamplona.edu.co',
        password='Admin1234',
        nombre='Admin Test',
        cedula='999000001',
        nombre_usuario='admin.test',
        rol=rol,
        requiere_cambio_contrasena=False,
        estado=Estado.ACTIVO,
    )
    permiso, _ = Permiso.objects.get_or_create(
        nombre='sistema.parametrizar',
        defaults={'descripcion': 'Acceso a parametrización', 'estado': 'Activo'},
    )
    RolPermiso.objects.get_or_create(rol=rol, permiso=permiso)
    return usuario


class DocumentosViewTests(TestCase):

    def setUp(self):
        self.admin = _crear_admin()
        self.client.force_login(self.admin)

    def test_lista_vacia(self):
        resp = self.client.get(reverse('parametrizacion:documentos'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Documentos y formatos')

    def test_crear_plantilla(self):
        resp = self.client.post(reverse('parametrizacion:documentos_nueva'), {
            'nombre': 'Formato propuesta',
            'tipo': 'propuesta',
            'descripcion': 'Plantilla Word para propuesta.',
            'estado': 'Activo',
        })
        self.assertRedirects(resp, reverse('parametrizacion:documentos'))
        self.assertTrue(Plantilla.objects.filter(nombre='Formato propuesta').exists())

    def test_editar_plantilla(self):
        plantilla = Plantilla.objects.create(
            nombre='Vieja', tipo='otro', descripcion='', estado='Activo'
        )
        resp = self.client.post(
            reverse('parametrizacion:documentos_editar', args=[plantilla.pk]),
            {'nombre': 'Nueva', 'tipo': 'informe', 'descripcion': '', 'estado': 'Activo'},
        )
        self.assertRedirects(resp, reverse('parametrizacion:documentos'))
        plantilla.refresh_from_db()
        self.assertEqual(plantilla.nombre, 'Nueva')

    def test_subir_version_guarda_en_documentos(self):
        """El archivo debe quedar dentro de MEDIA_ROOT/documentos/."""
        plantilla = Plantilla.objects.create(
            nombre='Propuesta', tipo='propuesta', descripcion='', estado='Activo'
        )
        archivo = io.BytesIO(b'contenido del archivo')
        archivo.name = 'plantilla.docx'
        resp = self.client.post(
            reverse('parametrizacion:documentos_version', args=[plantilla.pk]),
            {'archivo': archivo},
            format='multipart',
        )
        self.assertRedirects(resp, reverse('parametrizacion:documentos'))
        version = plantilla.versiones.get()
        self.assertTrue(version.es_vigente)
        # La ruta relativa debe empezar con 'documentos/'
        self.assertTrue(
            version.ruta_archivo.startswith('documentos' + os.sep) or
            version.ruta_archivo.startswith('documentos/'),
            msg=f'ruta_archivo debe empezar con documentos/: {version.ruta_archivo}',
        )
        # El archivo físico debe existir
        ruta_fisica = os.path.join(settings.MEDIA_ROOT, version.ruta_archivo)
        self.assertTrue(os.path.exists(ruta_fisica), msg=f'Archivo no existe en {ruta_fisica}')

    def test_segunda_version_desactiva_la_anterior(self):
        plantilla = Plantilla.objects.create(
            nombre='Informe', tipo='informe', descripcion='', estado='Activo'
        )
        for i in range(2):
            archivo = io.BytesIO(b'contenido')
            archivo.name = f'v{i + 1}.docx'
            self.client.post(
                reverse('parametrizacion:documentos_version', args=[plantilla.pk]),
                {'archivo': archivo},
                format='multipart',
            )
        self.assertEqual(plantilla.versiones.filter(es_vigente=True).count(), 1)
        self.assertEqual(plantilla.versiones.filter(es_vigente=True).first().numero_version, 2)

    def test_extension_invalida_rechazada(self):
        """Un archivo .exe debe ser rechazado por el formulario."""
        plantilla = Plantilla.objects.create(
            nombre='Test', tipo='otro', descripcion='', estado='Activo'
        )
        archivo = io.BytesIO(b'contenido')
        archivo.name = 'malicioso.exe'
        resp = self.client.post(
            reverse('parametrizacion:documentos_version', args=[plantilla.pk]),
            {'archivo': archivo},
            format='multipart',
        )
        # Debe quedarse en la misma página con error (200, no redirect)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(plantilla.versiones.count(), 0)

    def test_archivo_mayor_a_10mb_rechazado(self):
        """Un archivo de más de 10 MB debe ser rechazado."""
        plantilla = Plantilla.objects.create(
            nombre='Pesado', tipo='propuesta', descripcion='', estado='Activo'
        )
        archivo = io.BytesIO(b'x' * (10 * 1024 * 1024 + 1))
        archivo.name = 'grande.docx'
        resp = self.client.post(
            reverse('parametrizacion:documentos_version', args=[plantilla.pk]),
            {'archivo': archivo},
            format='multipart',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(plantilla.versiones.count(), 0)


class DescargaPlantillaTests(TestCase):
    """Tests de descarga de plantillas (ADMO y Director con permiso CSV)."""

    def setUp(self):
        self.admin = _crear_admin()
        # Plantilla propuesta
        self.plantilla = Plantilla.objects.create(
            nombre='Propuesta TS', tipo='propuesta', estado='Activo',
        )

    def _subir_version(self, plantilla, contenido=b'contenido', nombre='plantilla.docx'):
        """Helper: crea una VersionPlantilla directamente en BD."""
        import os
        from django.conf import settings
        directorio = os.path.join(settings.MEDIA_ROOT, 'documentos')
        os.makedirs(directorio, exist_ok=True)
        ruta_abs = os.path.join(directorio, nombre)
        with open(ruta_abs, 'wb') as f:
            f.write(contenido)
        return VersionPlantilla.objects.create(
            plantilla=plantilla,
            usuario=self.admin,
            numero_version=1,
            nombre_archivo=nombre,
            ruta_archivo=os.path.join('documentos', nombre),
            es_vigente=True,
        )

    def test_admo_descarga_plantilla_vigente(self):
        self._subir_version(self.plantilla)
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('parametrizacion:documentos_descargar', args=[self.plantilla.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp.get('Content-Disposition', ''))

    def test_admo_sin_version_redirige(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            reverse('parametrizacion:documentos_descargar', args=[self.plantilla.pk]),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)

    def _crear_director_con_permiso_csv(self):
        rol, _ = Rol.objects.get_or_create(nombre='Director', defaults={'estado': 'Activo'})
        usuario = Usuario.objects.create_user(
            correo_institucional='dir@unipamplona.edu.co',
            password='Director-Test-1',
            nombre='Director CSV',
            cedula='800000099',
            nombre_usuario='dir.csv',
            rol=rol,
            requiere_cambio_contrasena=False,
        )
        permiso, _ = Permiso.objects.get_or_create(
            nombre='estudiante.cargar_csv',
            defaults={'descripcion': 'Cargar CSV', 'estado': 'Activo'},
        )
        RolPermiso.objects.get_or_create(rol=rol, permiso=permiso)
        return usuario

    def test_director_descarga_csv_sin_version_cargada(self):
        """Sin versión vigente devuelve CSV básico con las 4 columnas."""
        director = self._crear_director_con_permiso_csv()
        self.client.force_login(director)
        resp = self.client.get(reverse('parametrizacion:plantilla_csv_estudiantes'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp.get('Content-Type', ''))
        contenido = b''.join(resp.streaming_content) if hasattr(resp, 'streaming_content') else resp.content
        primera_linea = contenido.decode('utf-8').strip().split('\r\n')[0]
        self.assertEqual(primera_linea, 'nombre,cedula,correo,carrera')

    def test_director_descarga_csv_con_version(self):
        """Con versión vigente cargada devuelve ese archivo."""
        plantilla_csv = Plantilla.objects.create(
            nombre='CSV Estudiantes', tipo='csv', estado='Activo',
        )
        self._subir_version(plantilla_csv, contenido=b'nombre,cedula,correo,carrera\n', nombre='est.csv')
        director = self._crear_director_con_permiso_csv()
        self.client.force_login(director)
        resp = self.client.get(reverse('parametrizacion:plantilla_csv_estudiantes'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp.get('Content-Disposition', ''))

    def test_sin_permiso_no_descarga_csv(self):
        """Un usuario sin estudiante.cargar_csv recibe 403."""
        rol, _ = Rol.objects.get_or_create(nombre='Estudiante', defaults={'estado': 'Activo'})
        usuario = Usuario.objects.create_user(
            correo_institucional='est2@unipamplona.edu.co',
            password='Est-Test-1',
            nombre='Est Sin Permiso',
            cedula='700000099',
            nombre_usuario='est2',
            rol=rol,
            requiere_cambio_contrasena=False,
        )
        self.client.force_login(usuario)
        resp = self.client.get(reverse('parametrizacion:plantilla_csv_estudiantes'))
        self.assertEqual(resp.status_code, 403)


class DescargaPlantillaPropuestaEstudianteTests(TestCase):
    """Tests de la descarga de plantilla de propuesta para Estudiante (SISTRA-01).

    URL: parametrizacion:plantilla_propuesta_estudiante
    Reglas:
      - Usuario autenticado → 200 si hay versión vigente, 404 si no hay.
      - Usuario no autenticado → redirige al login (LoginRequiredMixin).
    """

    def setUp(self):
        self.admin = _crear_admin()
        self.plantilla = Plantilla.objects.create(
            nombre='Propuesta TG', tipo='propuesta', estado='Activo',
        )

    def _crear_estudiante(self):
        rol, _ = Rol.objects.get_or_create(nombre='Estudiante', defaults={'estado': 'Activo'})
        return Usuario.objects.create_user(
            correo_institucional='est@unipamplona.edu.co',
            password='Est-Test-1',
            nombre='Estudiante Test',
            cedula='100999001',
            nombre_usuario='est',
            rol=rol,
            requiere_cambio_contrasena=False,
        )

    def _subir_version_propuesta(self, contenido=b'contenido propuesta', nombre='propuesta.docx'):
        import os
        from django.conf import settings
        directorio = os.path.join(settings.MEDIA_ROOT, 'documentos')
        os.makedirs(directorio, exist_ok=True)
        ruta_abs = os.path.join(directorio, nombre)
        with open(ruta_abs, 'wb') as f:
            f.write(contenido)
        return VersionPlantilla.objects.create(
            plantilla=self.plantilla,
            usuario=self.admin,
            numero_version=1,
            nombre_archivo=nombre,
            ruta_archivo=os.path.join('documentos', nombre),
            es_vigente=True,
        )

    def test_estudiante_descarga_propuesta_vigente(self):
        """El Estudiante puede descargar la plantilla de propuesta si hay versión vigente."""
        self._subir_version_propuesta()
        estudiante = self._crear_estudiante()
        self.client.force_login(estudiante)
        resp = self.client.get(reverse('parametrizacion:plantilla_propuesta_estudiante'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp.get('Content-Disposition', ''))

    def test_sin_version_vigente_devuelve_404(self):
        """Sin versión vigente cargada el Estudiante recibe 404."""
        estudiante = self._crear_estudiante()
        self.client.force_login(estudiante)
        resp = self.client.get(reverse('parametrizacion:plantilla_propuesta_estudiante'))
        self.assertEqual(resp.status_code, 404)

    def test_no_autenticado_redirige(self):
        """Sin sesión, redirige al login (no 403)."""
        resp = self.client.get(reverse('parametrizacion:plantilla_propuesta_estudiante'))
        self.assertEqual(resp.status_code, 302)

    def test_admo_tambien_puede_descargar(self):
        """El Administrador también puede acceder (es un usuario autenticado)."""
        self._subir_version_propuesta(nombre='propuesta_admo.docx')
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('parametrizacion:plantilla_propuesta_estudiante'))
        self.assertEqual(resp.status_code, 200)
