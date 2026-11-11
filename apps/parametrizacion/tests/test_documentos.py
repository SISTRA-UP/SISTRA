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
