from django.test import TestCase

from apps.seguimiento.models import Auditoria
from apps.usuarios.models import ROL_DIRECTOR, ROL_ESTUDIANTE
from apps.usuarios.servicios import crear_usuario


class CarreraYAuditoriaTests(TestCase):
    def crear(self, rol, **extra):
        datos = {'nombre': 'Ana Pérez', 'cedula': '1001234567',
                 'correo': 'ana@unipamplona.edu.co', 'rol': rol}
        datos.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return crear_usuario(**datos)

    def test_estudiante_queda_inscrito_en_derecho(self):
        inscripcion = self.crear(ROL_ESTUDIANTE).estudiante.inscripciones.get()
        self.assertEqual(inscripcion.carrera.codigo, '52382')
        self.assertEqual(inscripcion.estado, 'Activo')

    def test_director_se_crea_sin_carrera(self):
        usuario = self.crear(ROL_DIRECTOR)
        self.assertFalse(usuario.director.asignaciones.exists())

    def test_registra_auditoria_sin_secretos(self):
        usuario = self.crear(ROL_ESTUDIANTE)
        registro = Auditoria.objects.get(accion='Crear usuario')
        self.assertEqual(registro.id_registro_afectado, usuario.pk)
        self.assertNotIn('Contraseña', registro.detalle)