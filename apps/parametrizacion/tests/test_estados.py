"""SISTRA-11 · Parametrización: pruebas de estados del proceso (actividades y tipos de rechazo).

Se ejecutan con:
    uv run python manage.py test apps.parametrizacion.tests.test_estados
"""

from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Actividad, TipoRechazo
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso, Usuario


def _crear_admin():
    rol, _ = Rol.objects.get_or_create(nombre='Administrador', defaults={'estado': Estado.ACTIVO})
    usuario = Usuario.objects.create_user(
        correo_institucional='admin.estados@unipamplona.edu.co',
        password='Admin1234',
        nombre='Admin Estados',
        cedula='999000008',
        nombre_usuario='admin.estados',
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


def _crear_director():
    rol, _ = Rol.objects.get_or_create(nombre='Director', defaults={'estado': Estado.ACTIVO})
    return Usuario.objects.create_user(
        correo_institucional='director.estados@unipamplona.edu.co',
        password='Dir1234',
        nombre='Director Estados',
        cedula='999000009',
        nombre_usuario='director.estados',
        rol=rol,
        requiere_cambio_contrasena=False,
        estado=Estado.ACTIVO,
    )


class EstadosViewTests(TestCase):

    def setUp(self):
        self.admin = _crear_admin()
        self.director = _crear_director()
        self.client.force_login(self.admin)

    def test_sin_sesion_redirige(self):
        self.client.logout()
        resp = self.client.get(reverse('parametrizacion:estados'))
        self.assertEqual(resp.status_code, 302)

    def test_director_no_tiene_acceso(self):
        self.client.force_login(self.director)
        resp = self.client.get(reverse('parametrizacion:estados'))
        self.assertEqual(resp.status_code, 403)

    def test_admin_ve_lista_estados(self):
        # Usar orden 97 para no colisionar con las etapas sembradas (1-6)
        Actividad.objects.create(
            nombre='Propuesta de Trabajo Social',
            descripcion='Presentación inicial',
            orden=97,
            obligatoria=True,
            estado='Activo',
        )
        # Usar nombre único para no colisionar con TipoRechazo sembrados
        TipoRechazo.objects.create(
            nombre='Falta de acta de compromiso',
            descripcion='No adjunta acta',
            estado='Activo',
        )
        resp = self.client.get(reverse('parametrizacion:estados'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Estados del proceso')
        self.assertContains(resp, 'Propuesta de Trabajo Social')
        self.assertContains(resp, 'Falta de acta de compromiso')
        self.assertNotContains(resp, 'Borrador')

    def test_crear_actividad_exitosa(self):
        # Usar orden 98 para no colisionar con las etapas sembradas (1-6)
        resp = self.client.post(reverse('parametrizacion:actividad_nueva'), {
            'nombre': 'Informe Final',
            'descripcion': 'Entrega de informe al finalizar horas',
            'orden': 98,
            'obligatoria': True,
            'estado': 'Activo',
        })
        self.assertRedirects(resp, reverse('parametrizacion:estados'))
        self.assertTrue(Actividad.objects.filter(nombre='Informe Final', orden=98).exists())
        self.assertTrue(Auditoria.objects.filter(accion='Crear etapa del proceso').exists())

    def test_crear_actividad_orden_duplicado_falla(self):
        # La siembra ya creó orden=1; intentar crearlo de nuevo debe fallar
        resp = self.client.post(reverse('parametrizacion:actividad_nueva'), {
            'nombre': 'Otra etapa con orden 1',
            'descripcion': '',
            'orden': 1,
            'obligatoria': False,
            'estado': 'Activo',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ya existe una etapa con el orden 1')

    def test_editar_actividad(self):
        # Usar orden 99 para no colisionar con las etapas sembradas (1-6)
        actividad = Actividad.objects.create(
            nombre='Etapa Inicial', descripcion='', orden=99, obligatoria=True, estado='Activo'
        )
        resp = self.client.post(reverse('parametrizacion:actividad_editar', args=[actividad.pk]), {
            'nombre': 'Etapa Inicial Modificada',
            'descripcion': 'Nueva descripción',
            'orden': 99,
            'obligatoria': False,
            'estado': 'Inactivo',
        })
        self.assertRedirects(resp, reverse('parametrizacion:estados'))
        actividad.refresh_from_db()
        self.assertEqual(actividad.nombre, 'Etapa Inicial Modificada')
        self.assertEqual(actividad.estado, 'Inactivo')
        self.assertFalse(actividad.obligatoria)
        self.assertTrue(Auditoria.objects.filter(accion='Editar etapa del proceso').exists())

    def test_crear_tipo_rechazo_exitoso(self):
        resp = self.client.post(reverse('parametrizacion:rechazo_nuevo'), {
            'nombre': 'Tema no pertinente',
            'descripcion': 'El proyecto no cumple las líneas de acción',
            'estado': 'Activo',
        })
        self.assertRedirects(resp, reverse('parametrizacion:estados'))
        self.assertTrue(TipoRechazo.objects.filter(nombre='Tema no pertinente').exists())
        self.assertTrue(Auditoria.objects.filter(accion='Crear tipo de rechazo').exists())

    def test_crear_tipo_rechazo_nombre_duplicado_falla(self):
        TipoRechazo.objects.create(nombre='Plagio', descripcion='', estado='Activo')
        resp = self.client.post(reverse('parametrizacion:rechazo_nuevo'), {
            'nombre': 'Plagio',
            'descripcion': 'Copia sin citar',
            'estado': 'Activo',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ya existe un tipo de rechazo con el nombre')

    def test_editar_tipo_rechazo(self):
        tipo = TipoRechazo.objects.create(
            nombre='Falta firma', descripcion='', estado='Activo'
        )
        resp = self.client.post(reverse('parametrizacion:rechazo_editar', args=[tipo.pk]), {
            'nombre': 'Falta firma del director de proyecto',
            'descripcion': 'Requiere visto bueno',
            'estado': 'Inactivo',
        })
        self.assertRedirects(resp, reverse('parametrizacion:estados'))
        tipo.refresh_from_db()
        self.assertEqual(tipo.nombre, 'Falta firma del director de proyecto')
        self.assertEqual(tipo.estado, 'Inactivo')
        self.assertTrue(Auditoria.objects.filter(accion='Editar tipo de rechazo').exists())

    def test_eliminar_actividad(self):
        actividad = Actividad.objects.create(
            nombre='Etapa para borrar', descripcion='', orden=9, obligatoria=False, estado='Activo'
        )
        resp = self.client.post(reverse('parametrizacion:actividad_eliminar', args=[actividad.pk]))
        self.assertRedirects(resp, reverse('parametrizacion:estados'))
        self.assertFalse(Actividad.objects.filter(pk=actividad.pk).exists())
        self.assertTrue(Auditoria.objects.filter(accion='Eliminar etapa del proceso').exists())

    def test_eliminar_tipo_rechazo(self):
        tipo = TipoRechazo.objects.create(
            nombre='Rechazo para borrar', descripcion='', estado='Activo'
        )
        resp = self.client.post(reverse('parametrizacion:rechazo_eliminar', args=[tipo.pk]))
        self.assertRedirects(resp, reverse('parametrizacion:estados'))
        self.assertFalse(TipoRechazo.objects.filter(pk=tipo.pk).exists())
        self.assertTrue(Auditoria.objects.filter(accion='Eliminar tipo de rechazo').exists())

