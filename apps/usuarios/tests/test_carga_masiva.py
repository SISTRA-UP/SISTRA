from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.seguimiento.models import Auditoria
from apps.usuarios.cargas import ErrorArchivo, log_errores_csv, procesar_csv
from apps.usuarios.models import Usuario

ENC = 'nombre,apellido,cc,correo,telefono,carrera\n'


def archivo(texto, codificacion='utf-8'):
    return SimpleUploadedFile('estudiantes.csv', texto.encode(codificacion))


class CargaMasivaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            'admin@unipamplona.edu.co', 'Clave-Segura-123',
            nombre='Admin', cedula='900000001', nombre_usuario='admin',
        )

    def cargar(self, texto, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return procesar_csv(archivo(texto, **kw), usuario=self.admin)

    def resultados(self, carga):
        return list(carga.filas.order_by('numero_fila').values_list('resultado', flat=True))

    def test_crea_estudiantes_e_ignora_filas_vacias(self):
        carga = self.cargar(
            ENC + 'Ana,Pérez,1.001.234.567,Ana@unipamplona.edu.co,300 123 4567,Derecho\n,,,,,\n,,,,,\n'
        )
        self.assertEqual((carga.total_filas, carga.creadas, carga.con_error), (1, 1, 0))
        usuario = Usuario.objects.get(cedula='1001234567')
        self.assertEqual(usuario.nombre, 'Ana Pérez')
        self.assertEqual(usuario.telefono, '3001234567')
        self.assertEqual(usuario.correo_institucional, 'ana@unipamplona.edu.co')
        self.assertEqual(usuario.estudiante.inscripciones.get().carrera.codigo, '52382')

    def test_acepta_punto_y_coma_y_windows_1252(self):
        texto = 'nombre;apellido;cc;correo;telefono;carrera\nLuis;Díaz;1007654321;luis@unipamplona.edu.co;;52382\n'
        carga = self.cargar(texto, codificacion='cp1252')
        self.assertEqual(carga.creadas, 1)
        self.assertEqual(Usuario.objects.get(cedula='1007654321').nombre, 'Luis Díaz')

    def test_una_fila_mala_no_tumba_las_demas(self):
        carga = self.cargar(
            ENC
            + 'Ana,Pérez,1001234567,ana@unipamplona.edu.co,,Derecho\n'
            + 'Bad,Correo,1002345678,bad@gmail.com,,Derecho\n'
            + 'Eva,Ruiz,1003456789,eva@unipamplona.edu.co,,Derecho\n'
        )
        self.assertEqual(self.resultados(carga), ['Creada', 'Error', 'Creada'])
        self.assertEqual((carga.creadas, carga.con_error), (2, 1))
        self.assertTrue(Auditoria.objects.filter(accion='Carga masiva de estudiantes', resultado='Parcial').exists())

    def test_cedula_repetida_en_el_archivo(self):
        carga = self.cargar(
            ENC
            + 'Ana,Pérez,1001234567,ana@unipamplona.edu.co,,Derecho\n'
            + 'Otra,Ana,1001234567,otra@unipamplona.edu.co,,Derecho\n'
        )
        self.assertEqual(self.resultados(carga), ['Creada', 'Error'])

    def test_carrera_inexistente(self):
        carga = self.cargar(ENC + 'Ana,Pérez,1001234567,ana@unipamplona.edu.co,,Medicina\n')
        self.assertEqual(self.resultados(carga), ['Error'])
        self.assertIn('Medicina', carga.filas.get().detalle)

    def test_existente_con_mismo_correo_actualiza_sin_tocar_clave_ni_correo(self):
        self.cargar(ENC + 'Ana,Pérez,1001234567,ana@unipamplona.edu.co,,Derecho\n')
        antes = Usuario.objects.get(cedula='1001234567').password
        carga = self.cargar(ENC + 'Ana María,Pérez,1001234567,ana@unipamplona.edu.co,3009998888,Derecho\n')
        self.assertEqual(self.resultados(carga), ['Actualizada'])
        usuario = Usuario.objects.get(cedula='1001234567')
        self.assertEqual(usuario.nombre, 'Ana María Pérez')
        self.assertEqual(usuario.telefono, '3009998888')
        self.assertEqual(usuario.password, antes)

    def test_cedula_existente_con_otro_correo_es_error(self):
        self.cargar(ENC + 'Ana,Pérez,1001234567,ana@unipamplona.edu.co,,Derecho\n')
        carga = self.cargar(ENC + 'Ana,Pérez,1001234567,otro@unipamplona.edu.co,,Derecho\n')
        self.assertEqual(self.resultados(carga), ['Error'])
        self.assertEqual(Usuario.objects.filter(cedula='1001234567').count(), 1)

    def test_faltan_columnas(self):
        with self.assertRaises(ErrorArchivo):
            self.cargar('nombre,cc\nAna,1001234567\n')

    @override_settings(CARGA_MASIVA_MAX_FILAS=1)
    def test_supera_el_maximo_de_filas(self):
        with self.assertRaises(ErrorArchivo):
            self.cargar(
                ENC + 'A,B,1001234567,a@unipamplona.edu.co,,Derecho\n'
                + 'C,D,1002345678,c@unipamplona.edu.co,,Derecho\n'
            )

    def test_log_neutraliza_formulas(self):
        carga = self.cargar(ENC + 'Ana,Pérez,1001234567,=1+1@unipamplona.edu.co,,Derecho\n')
        contenido = log_errores_csv(carga).decode('utf-8-sig')
        self.assertIn("'=1+1@unipamplona.edu.co", contenido)