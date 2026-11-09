import re

from django.core import mail
from django.test import TestCase, override_settings

from apps.usuarios.models import ROL_ADMINISTRADOR, ROL_DIRECTOR, ROL_ESTUDIANTE, Estado, Usuario
from apps.usuarios.servicios import (
    ErrorCreacion, crear_usuario, derivar_nombre_usuario, generar_contrasena_temporal,
)


class CrearUsuarioTests(TestCase):
    def crear(self, **cambios):
        datos = {
            'nombre': 'Ana Pérez', 'cedula': '1001234567',
            'correo': 'Ana.Perez@unipamplona.edu.co', 'rol': ROL_ESTUDIANTE,
        }
        datos.update(cambios)
        with self.captureOnCommitCallbacks(execute=True):
            return crear_usuario(**datos)

    def test_crea_estudiante_con_perfil_y_clave_temporal(self):
        usuario = self.crear()
        self.assertEqual(usuario.correo_institucional, 'ana.perez@unipamplona.edu.co')
        self.assertEqual(usuario.nombre_usuario, 'ana.perez')
        self.assertEqual(usuario.estado, Estado.ACTIVO)
        self.assertTrue(usuario.requiere_cambio_contrasena)
        self.assertTrue(hasattr(usuario, 'estudiante'))
        self.assertEqual(len(mail.outbox), 1)
        clave = re.search(r'Contraseña temporal: (\S+)', mail.outbox[0].body).group(1)
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(clave))
        self.assertNotEqual(usuario.password, clave)

    def test_crea_director(self):
        usuario = self.crear(rol=ROL_DIRECTOR)
        self.assertTrue(hasattr(usuario, 'director'))

    def test_rechaza_rol_administrador(self):
        with self.assertRaises(ErrorCreacion):
            self.crear(rol=ROL_ADMINISTRADOR)

    def test_rechaza_cedula_duplicada(self):
        self.crear()
        with self.assertRaisesMessage(ErrorCreacion, 'cédula'):
            self.crear(correo='otra@unipamplona.edu.co')

    def test_rechaza_correo_duplicado_sin_importar_mayusculas(self):
        self.crear()
        with self.assertRaisesMessage(ErrorCreacion, 'correo'):
            self.crear(cedula='2002345678', correo='ANA.PEREZ@UNIPAMPLONA.EDU.CO')

    def test_rechaza_cedula_con_letras(self):
        with self.assertRaises(ErrorCreacion):
            self.crear(cedula='12ab5')

    def test_nombre_usuario_repetido_recibe_sufijo(self):
        self.crear(correo='ana@unipamplona.edu.co')
        self.assertEqual(derivar_nombre_usuario('ana@otro.edu.co'), 'ana2')

    @override_settings(DOMINIOS_CORREO_PERMITIDOS=['unipamplona.edu.co'])
    def test_rechaza_dominio_no_institucional(self):
        with self.assertRaises(ErrorCreacion):
            self.crear(correo='ana@gmail.com')

    def test_si_falla_no_se_envia_correo_ni_se_crea_usuario(self):
        with self.assertRaises(ErrorCreacion):
            self.crear(cedula='abc')
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Usuario.objects.count(), 0)

    def test_contrasena_temporal_mezcla_tipos(self):
        clave = generar_contrasena_temporal()
        self.assertEqual(len(clave), 12)
        self.assertTrue(any(c.isupper() for c in clave))
        self.assertTrue(any(c.islower() for c in clave))
        self.assertTrue(any(c.isdigit() for c in clave))