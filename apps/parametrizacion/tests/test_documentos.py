"""SISTRA-11 · Parametrización: pruebas de documentos y formatos.

Se ejecutan con:
    uv run python manage.py test apps.parametrizacion.tests.test_documentos
"""

import io

from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Plantilla, VersionPlantilla
from apps.usuarios.models import Estado, Rol, Usuario


def _crear_admin():
    rol, _ = Rol.objects.get_or_create(nombre='Administrador', defaults={'estado': Estado.ACTIVO})
    return Usuario.objects.create_user(
        correo_institucional='admin@unipamplona.edu.co',
        password='Admin1234',
        nombre='Admin Test',
        cedula='999000001',
        nombre_usuario='admin.test',
        rol=rol,
        requiere_cambio_contrasena=False,
        estado=Estado.ACTIVO,
    )


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

    def test_subir_version(self):
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
        self.assertEqual(plantilla.versiones.count(), 1)
        self.assertTrue(plantilla.versiones.first().es_vigente)

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
