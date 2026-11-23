from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import Carrera, Facultad
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso, Usuario


def _crear_usuario(correo, cedula, nombre_usuario, nombre_rol):
    rol, _ = Rol.objects.get_or_create(nombre=nombre_rol, defaults={'estado': Estado.ACTIVO})
    return Usuario.objects.create_user(
        correo_institucional=correo,
        password='Clave-Segura-123',
        nombre=nombre_usuario,
        cedula=cedula,
        nombre_usuario=nombre_usuario,
        rol=rol,
        requiere_cambio_contrasena=False,
        estado=Estado.ACTIVO,
    )


class FacultadesCarrerasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _crear_usuario(
            'admin.catalogos@unipamplona.edu.co', '999000101', 'admin.catalogos', 'Administrador'
        )
        permiso, _ = Permiso.objects.get_or_create(
            nombre='sistema.parametrizar',
            defaults={'descripcion': 'Acceso a parametrización', 'estado': Estado.ACTIVO},
        )
        RolPermiso.objects.get_or_create(rol=cls.admin.rol, permiso=permiso)
        cls.director = _crear_usuario(
            'director.catalogos@unipamplona.edu.co', '999000102', 'director.catalogos', 'Director'
        )
        cls.estudiante = _crear_usuario(
            'estudiante.catalogos@unipamplona.edu.co', '999000103', 'estudiante.catalogos', 'Estudiante'
        )
        cls.facultad = Facultad.objects.create(nombre='Facultad de prueba', estado=Estado.ACTIVO)
        cls.otra_facultad = Facultad.objects.create(nombre='Otra facultad', estado=Estado.ACTIVO)
        cls.carrera = Carrera.objects.create(
            nombre='Carrera de prueba', codigo='CP-01', facultad=cls.facultad,
            estado=Estado.ACTIVO,
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.lista = reverse('parametrizacion:facultades_carreras')

    def test_listado_muestra_facultades_y_carreras(self):
        respuesta = self.client.get(self.lista)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Facultad de prueba')
        self.assertContains(respuesta, 'Carrera de prueba')
        self.assertContains(respuesta, 'CP-01')

    def test_crea_facultad_y_audita(self):
        respuesta = self.client.post(reverse('parametrizacion:facultad_nueva'), {
            'nombre': 'Facultad nueva', 'descripcion': 'Descripción de prueba', 'estado': 'Activo',
        })
        self.assertRedirects(respuesta, self.lista)
        self.assertTrue(Facultad.objects.filter(nombre='Facultad nueva').exists())
        self.assertTrue(Auditoria.objects.filter(accion='Crear facultad', resultado='Éxito').exists())

    def test_nombre_de_facultad_repetido_muestra_error_y_audita_fallo(self):
        respuesta = self.client.post(reverse('parametrizacion:facultad_nueva'), {
            'nombre': 'FACULTAD DE PRUEBA', 'descripcion': '', 'estado': 'Activo',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya existe una facultad con ese nombre.')
        self.assertTrue(Auditoria.objects.filter(accion='Crear facultad', resultado='Fallo').exists())

    def test_edita_e_inactiva_facultad_sin_eliminarla(self):
        url = reverse('parametrizacion:facultad_editar', args=[self.facultad.pk])
        respuesta = self.client.post(url, {
            'nombre': 'Facultad actualizada', 'descripcion': '', 'estado': 'Inactivo',
        })
        self.assertRedirects(respuesta, self.lista)
        self.facultad.refresh_from_db()
        self.assertEqual(self.facultad.estado, Estado.INACTIVO)
        self.assertTrue(Facultad.objects.filter(pk=self.facultad.pk).exists())
        self.assertTrue(Auditoria.objects.filter(accion='Inactivar facultad', resultado='Éxito').exists())

    def test_crea_carrera_asociada_y_audita(self):
        respuesta = self.client.post(reverse('parametrizacion:carrera_nueva'), {
            'nombre': 'Carrera nueva', 'codigo': 'CN-01',
            'facultad': self.facultad.pk, 'estado': 'Activo',
        })
        self.assertRedirects(respuesta, self.lista)
        carrera = Carrera.objects.get(codigo='CN-01')
        self.assertEqual(carrera.facultad, self.facultad)
        self.assertTrue(Auditoria.objects.filter(accion='Crear carrera', resultado='Éxito').exists())

    def test_edita_carrera_cambiando_facultad(self):
        respuesta = self.client.post(reverse('parametrizacion:carrera_editar', args=[self.carrera.pk]), {
            'nombre': 'Carrera de prueba', 'codigo': 'CP-01',
            'facultad': self.otra_facultad.pk, 'estado': 'Activo',
        })
        self.assertRedirects(respuesta, self.lista)
        self.carrera.refresh_from_db()
        self.assertEqual(self.carrera.facultad, self.otra_facultad)
        self.assertTrue(Auditoria.objects.filter(accion='Editar carrera', resultado='Éxito').exists())

    def test_codigo_repetido_muestra_error_y_audita_fallo(self):
        respuesta = self.client.post(reverse('parametrizacion:carrera_nueva'), {
            'nombre': 'Otra carrera', 'codigo': 'cp-01',
            'facultad': self.otra_facultad.pk, 'estado': 'Activo',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya existe una carrera con ese código.')
        self.assertTrue(Auditoria.objects.filter(accion='Crear carrera', resultado='Fallo').exists())

    def test_nombre_repetido_solo_se_rechaza_en_la_misma_facultad(self):
        url = reverse('parametrizacion:carrera_nueva')
        respuesta = self.client.post(url, {
            'nombre': 'CARRERA DE PRUEBA', 'codigo': 'CP-02',
            'facultad': self.facultad.pk, 'estado': 'Activo',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya existe una carrera con ese nombre en la facultad seleccionada.')

        respuesta = self.client.post(url, {
            'nombre': 'Carrera de prueba', 'codigo': 'CP-03',
            'facultad': self.otra_facultad.pk, 'estado': 'Activo',
        })
        self.assertRedirects(respuesta, self.lista)
        self.assertTrue(Carrera.objects.filter(codigo='CP-03', facultad=self.otra_facultad).exists())

    def test_inactiva_carrera_sin_eliminarla(self):
        respuesta = self.client.post(reverse('parametrizacion:carrera_editar', args=[self.carrera.pk]), {
            'nombre': 'Carrera de prueba', 'codigo': 'CP-01',
            'facultad': self.facultad.pk, 'estado': 'Inactivo',
        })
        self.assertRedirects(respuesta, self.lista)
        self.carrera.refresh_from_db()
        self.assertEqual(self.carrera.estado, Estado.INACTIVO)
        self.assertTrue(Auditoria.objects.filter(accion='Inactivar carrera', resultado='Éxito').exists())

    def test_director_y_estudiante_reciben_403_en_todas_las_rutas_nuevas(self):
        rutas = [
            ('get', reverse('parametrizacion:facultades_carreras')),
            ('get', reverse('parametrizacion:facultad_nueva')),
            ('post', reverse('parametrizacion:facultad_nueva'), {
                'nombre': 'Facultad nueva', 'descripcion': '', 'estado': 'Activo',
            }),
            ('get', reverse('parametrizacion:facultad_editar', args=[self.facultad.pk])),
            ('post', reverse('parametrizacion:facultad_editar', args=[self.facultad.pk]), {
                'nombre': 'Facultad de prueba', 'descripcion': '', 'estado': 'Activo',
            }),
            ('get', reverse('parametrizacion:carrera_nueva')),
            ('post', reverse('parametrizacion:carrera_nueva'), {
                'nombre': 'Carrera nueva', 'codigo': 'CN-02',
                'facultad': self.facultad.pk, 'estado': 'Activo',
            }),
            ('get', reverse('parametrizacion:carrera_editar', args=[self.carrera.pk])),
            ('post', reverse('parametrizacion:carrera_editar', args=[self.carrera.pk]), {
                'nombre': 'Carrera de prueba', 'codigo': 'CP-01',
                'facultad': self.facultad.pk, 'estado': 'Activo',
            }),
        ]
        for usuario in (self.director, self.estudiante):
            self.client.force_login(usuario)
            for operacion in rutas:
                metodo, ruta = operacion[0], operacion[1]
                with self.subTest(usuario=usuario.rol.nombre, ruta=ruta):
                    if metodo == 'post':
                        respuesta = self.client.post(ruta, operacion[2])
                    else:
                        respuesta = self.client.get(ruta)
                    self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(
            Auditoria.objects.filter(
                accion='Acceso bloqueado a facultades y carreras', resultado='Bloqueado'
            ).count(),
            len(rutas) * 2,
        )
