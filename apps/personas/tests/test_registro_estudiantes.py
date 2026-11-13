"""SISTRA-10 · Roles (registro de estudiantes): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

import csv

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad, Parametro
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import ProcesoTrabajoSocial
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Permiso, Rol, RolPermiso

Usuario = get_user_model()

PERMISOS_DEL_REGISTRO = ['estudiante.registrar', 'estudiante.cargar_csv']


class BaseRegistro(TestCase):
    """Un Director con su carrera asignada, listo para registrar.

    Los roles y los permisos los siembran las migraciones de datos.
    """

    def setUp(self):
        self.rol_director = Rol.objects.get(nombre='Director')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.rol_administrador = Rol.objects.get(nombre='Administrador')
        self.carrera = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')
        self.otra_carrera = self.crear_carrera('Ingeniería Civil', 'IC-01')
        self.director = self.crear_usuario(
            'dora.prado@ejemplo.edu.co', 'Dora Prado', '1000000001', self.rol_director
        )
        self.asignar_carrera(self.director, self.carrera)
        self.client.force_login(self.director)
        self.url = reverse('personas:estudiantes')
        self.url_csv = reverse('personas:estudiantes_csv')

    def crear_carrera(self, nombre, codigo):
        facultad, _ = Facultad.objects.get_or_create(nombre='Facultad de Prueba')
        return Carrera.objects.create(facultad=facultad, nombre=nombre, codigo=codigo)

    def crear_usuario(self, correo, nombre, cedula, rol):
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password='ClaveDePrueba123',
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=correo.split('@')[0],
            rol=rol,
            requiere_cambio_contrasena=False,
        )

    def asignar_carrera(self, usuario, carrera):
        director, _ = Director.objects.get_or_create(usuario=usuario)
        return DirectorCarrera.objects.create(
            director=director,
            carrera=carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )

    def registrar(self, follow=False, **cambios):
        datos = {
            'nombre': 'Laura Peña',
            'cedula': '1020304050',
            'correo': 'laura.pena@ejemplo.edu.co',
        }
        datos.update(cambios)
        return self.client.post(self.url, datos, follow=follow)

    def csv_de(self, filas, columnas=None, delimitador=','):
        columnas = columnas or ['nombre', 'cedula', 'correo', 'carrera']
        lineas = [delimitador.join(columnas)]
        for fila in filas:
            lineas.append(delimitador.join(fila))
        return '\n'.join(lineas)

    def subir(self, contenido, nombre='estudiantes.csv', codificacion='utf-8'):
        archivo = SimpleUploadedFile(
            nombre, contenido.encode(codificacion), content_type='text/csv'
        )
        return self.client.post(self.url_csv, {'archivo': archivo})

    def inscripciones_de(self, correo):
        return EstudianteCarrera.objects.filter(estudiante__usuario__correo_institucional=correo)


class SiembraDeLosPermisos(BaseRegistro):
    """C0 · sin los permisos sembrados el Director no puede entrar a nada."""

    def test_existen_los_dos_permisos(self):
        sembrados = set(Permiso.objects.values_list('nombre', flat=True))
        self.assertTrue(set(PERMISOS_DEL_REGISTRO).issubset(sembrados))

    def test_el_director_los_tiene(self):
        for permiso in PERMISOS_DEL_REGISTRO:
            self.assertTrue(
                self.director.has_perm(permiso), f'al Director le falta {permiso}'
            )

    def test_el_estudiante_no_los_tiene(self):
        estudiante = self.crear_usuario(
            'sin.permisos@ejemplo.edu.co', 'Sin Permisos', '1099999999', self.rol_estudiante
        )
        for permiso in PERMISOS_DEL_REGISTRO:
            self.assertFalse(estudiante.has_perm(permiso))

    def test_los_permisos_estan_asignados_al_rol_director(self):
        asignados = set(
            RolPermiso.objects.filter(rol=self.rol_director).values_list(
                'permiso__nombre', flat=True
            )
        )
        self.assertTrue(set(PERMISOS_DEL_REGISTRO).issubset(asignados))


class RegistroUnoAUno(BaseRegistro):
    """C1 y C4 · el Director registra uno a uno y se le genera la cuenta."""

    def test_la_pantalla_abre_con_las_dos_opciones(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Uno a uno')
        self.assertContains(respuesta, 'Archivo CSV')

    def test_la_pantalla_dice_en_que_carrera_registra(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'Ingeniería de Sistemas')

    def test_crea_la_cuenta_con_rol_estudiante(self):
        respuesta = self.registrar()
        self.assertRedirects(respuesta, self.url)
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre, 'Laura Peña')
        self.assertEqual(usuario.rol, self.rol_estudiante)

    def test_el_nombre_de_usuario_sale_del_correo(self):
        self.registrar()
        self.assertEqual(
            Usuario.objects.get(cedula='1020304050').nombre_usuario, 'laura.pena'
        )

    def test_la_contrasena_es_temporal_y_cifrada(self):
        self.registrar()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertTrue(usuario.requiere_cambio_contrasena)
        self.assertTrue(usuario.password.startswith('pbkdf2_'))

    def test_la_contrasena_no_se_muestra_en_pantalla(self):
        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value='ClaveTemporalDePrueba',
        ):
            respuesta = self.registrar()
        self.assertNotContains(self.client.get(respuesta.url), 'ClaveTemporalDePrueba')

    def test_lo_inscribe_en_la_carrera_del_director(self):
        self.registrar()
        inscripcion = self.inscripciones_de('laura.pena@ejemplo.edu.co').get()
        self.assertEqual(inscripcion.carrera, self.carrera)
        self.assertEqual(inscripcion.estado, EstadoInscripcion.ACTIVO)

    def test_le_crea_su_proceso_de_trabajo_social(self):
        self.registrar()
        inscripcion = self.inscripciones_de('laura.pena@ejemplo.edu.co').get()
        proceso = ProcesoTrabajoSocial.objects.get(estudiante_carrera=inscripcion)
        self.assertEqual(proceso.estado, 'Pendiente')
        self.assertIsNone(proceso.fecha_finalizacion)

    def test_le_crea_su_perfil_de_estudiante(self):
        self.registrar()
        self.assertTrue(
            Estudiante.objects.filter(
                usuario__correo_institucional='laura.pena@ejemplo.edu.co'
            ).exists()
        )

    def test_no_se_le_pide_la_carrera(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(
            set(respuesta.context['formulario'].fields), {'nombre', 'cedula', 'correo'}
        )

    def test_el_registro_queda_en_auditoria(self):
        self.registrar()
        registro = Auditoria.objects.filter(accion='Registrar estudiante').latest(
            'id_auditoria'
        )
        self.assertEqual(registro.usuario, self.director)
        self.assertIn('Ingeniería de Sistemas', registro.detalle)

    def test_sin_el_permiso_no_se_puede_registrar(self):
        estudiante = self.crear_usuario(
            'otro@ejemplo.edu.co', 'Otro', '1088888888', self.rol_estudiante
        )
        self.client.force_login(estudiante)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.registrar().status_code, 403)

    def test_un_director_sin_carrera_no_puede_registrar(self):
        suelto = self.crear_usuario(
            'sin.carrera@ejemplo.edu.co', 'Sin Carrera', '1077777777', self.rol_director
        )
        self.client.force_login(suelto)
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No tienes una carrera asignada')
        self.registrar()
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())


class ValidacionDeLosDatos(BaseRegistro):
    """C2 · valida el formato y los campos, y dice qué está mal."""

    def test_la_cedula_solo_acepta_digitos(self):
        respuesta = self.registrar(cedula='10A20B30')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(nombre='Laura Peña').exists())

    def test_el_correo_tiene_que_ser_valido(self):
        respuesta = self.registrar(correo='laura.pena-arroba-ejemplo')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_el_nombre_es_obligatorio(self):
        respuesta = self.registrar(nombre='')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_la_cedula_ya_usada_con_otro_correo_se_rechaza(self):
        self.crear_usuario(
            'otra.persona@ejemplo.edu.co', 'Otra Persona', '1020304050', self.rol_estudiante
        )
        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'ya está registrada con otro correo')

    def test_el_correo_ya_usado_con_otra_cedula_se_rechaza(self):
        self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Otra Laura', '1066666666', self.rol_estudiante
        )
        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'ya está registrado con otra cédula')

    def test_una_cedula_de_un_director_no_se_registra_como_estudiante(self):
        respuesta = self.registrar(
            cedula=self.director.cedula, correo=self.director.correo_institucional
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'rol Director')


class EstudianteYaRegistrado(BaseRegistro):
    """C3 · los tres casos: omitir, agregar la inscripción o completar.

    El tercero existe porque el PO aceptó que el ADMO cree un Estudiante sin
    carrera: si se tratara como «ya existe, lo omito», ese estudiante nunca
    podría empezar su Trabajo Social.
    """

    def test_ya_inscrito_en_esta_carrera_se_omite(self):
        self.registrar()
        self.registrar()
        self.assertEqual(self.inscripciones_de('laura.pena@ejemplo.edu.co').count(), 1)
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)

    def test_al_omitirlo_se_le_avisa_al_director(self):
        self.registrar()
        respuesta = self.client.post(
            self.url,
            {
                'nombre': 'Laura Peña',
                'cedula': '1020304050',
                'correo': 'laura.pena@ejemplo.edu.co',
            },
            follow=True,
        )
        self.assertContains(respuesta, 'ya estaba registrado')

    def test_al_omitirlo_no_se_le_manda_otro_correo(self):
        self.registrar()
        mail.outbox.clear()
        self.registrar()
        self.assertEqual(len(mail.outbox), 0)

    def test_inscrito_en_otra_carrera_solo_suma_la_inscripcion(self):
        otro_director = self.crear_usuario(
            'luis.mora@ejemplo.edu.co', 'Luis Mora', '1055555555', self.rol_director
        )
        self.asignar_carrera(otro_director, self.otra_carrera)
        self.client.force_login(otro_director)
        self.registrar()

        self.client.force_login(self.director)
        self.registrar()

        inscripciones = self.inscripciones_de('laura.pena@ejemplo.edu.co')
        self.assertEqual(inscripciones.count(), 2)
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)
        self.assertEqual(
            set(inscripciones.values_list('carrera__nombre', flat=True)),
            {'Ingeniería de Sistemas', 'Ingeniería Civil'},
        )

    def test_cada_carrera_tiene_su_propio_proceso(self):
        otro_director = self.crear_usuario(
            'luis.mora@ejemplo.edu.co', 'Luis Mora', '1055555555', self.rol_director
        )
        self.asignar_carrera(otro_director, self.otra_carrera)
        self.client.force_login(otro_director)
        self.registrar()
        self.client.force_login(self.director)
        self.registrar()
        self.assertEqual(
            ProcesoTrabajoSocial.objects.filter(
                estudiante_carrera__estudiante__usuario__cedula='1020304050'
            ).count(),
            2,
        )

    def test_a_un_estudiante_ya_existente_no_se_le_manda_contrasena_nueva(self):
        otro_director = self.crear_usuario(
            'luis.mora@ejemplo.edu.co', 'Luis Mora', '1055555555', self.rol_director
        )
        self.asignar_carrera(otro_director, self.otra_carrera)
        self.client.force_login(otro_director)
        self.registrar()
        clave = Usuario.objects.get(cedula='1020304050').password

        self.client.force_login(self.director)
        mail.outbox.clear()
        self.registrar()

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Usuario.objects.get(cedula='1020304050').password, clave)

    def test_una_cuenta_sin_ninguna_inscripcion_se_completa_no_se_omite(self):
        # Es el usuario que crea el ADMO: existe, pero sin carrera ni proceso.
        creado_por_el_admo = self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        self.assertFalse(Estudiante.objects.filter(usuario=creado_por_el_admo).exists())

        self.registrar()

        self.assertTrue(Estudiante.objects.filter(usuario=creado_por_el_admo).exists())
        inscripcion = self.inscripciones_de('laura.pena@ejemplo.edu.co').get()
        self.assertEqual(inscripcion.carrera, self.carrera)
        self.assertTrue(
            ProcesoTrabajoSocial.objects.filter(estudiante_carrera=inscripcion).exists()
        )
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)

    def test_completar_una_cuenta_queda_en_auditoria(self):
        self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        self.registrar()
        self.assertTrue(
            Auditoria.objects.filter(accion='Inscribir estudiante en carrera').exists()
        )


class CorreoDeCredenciales(BaseRegistro):
    """C5 · el usuario y la contraseña temporal van al correo institucional."""

    def test_se_manda_un_correo_al_estudiante_nuevo(self):
        mail.outbox.clear()
        self.registrar()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['laura.pena@ejemplo.edu.co'])

    def test_el_correo_lleva_el_usuario_de_ingreso_y_la_contrasena(self):
        mail.outbox.clear()
        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value='ClaveTemporalDePrueba',
        ):
            self.registrar()
        cuerpo = mail.outbox[0].body
        self.assertIn('laura.pena@ejemplo.edu.co', cuerpo)
        self.assertIn('ClaveTemporalDePrueba', cuerpo)

    def test_el_envio_queda_en_auditoria(self):
        self.registrar()
        registro = Auditoria.objects.filter(accion='Enviar credenciales').latest(
            'id_auditoria'
        )
        self.assertEqual(registro.resultado, 'Éxito')

    def test_si_el_correo_falla_la_cuenta_queda_creada_igual(self):
        # EX-03 del BRD: la cuenta se crea y el fallo se registra para reenviar.
        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=OSError('sin servicio de correo'),
        ):
            respuesta = self.registrar()
        self.assertRedirects(respuesta, self.url)
        self.assertTrue(Usuario.objects.filter(cedula='1020304050').exists())
        registro = Auditoria.objects.filter(accion='Enviar credenciales').latest(
            'id_auditoria'
        )
        self.assertEqual(registro.resultado, 'Fallo')

    def test_si_el_correo_falla_el_estudiante_igual_queda_inscrito(self):
        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=OSError('sin servicio de correo'),
        ):
            self.registrar()
        self.assertEqual(self.inscripciones_de('laura.pena@ejemplo.edu.co').count(), 1)


class CargueCsv(BaseRegistro):
    """C1 y C2 · el cargue masivo procesa fila por fila y reporta los errores."""

    def fila(self, nombre, cedula, correo, carrera='Ingeniería de Sistemas'):
        return [nombre, cedula, correo, carrera]

    def test_registra_las_filas_validas(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)
        self.assertEqual(Usuario.objects.filter(rol=self.rol_estudiante).count(), 2)

    def test_a_cada_uno_le_crea_inscripcion_y_proceso(self):
        contenido = self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')])
        self.subir(contenido)
        inscripcion = self.inscripciones_de('ana.gil@ejemplo.edu.co').get()
        self.assertEqual(inscripcion.carrera, self.carrera)
        self.assertTrue(
            ProcesoTrabajoSocial.objects.filter(estudiante_carrera=inscripcion).exists()
        )

    def test_las_filas_malas_no_tumban_las_buenas(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
                self.fila('Mala Fila', 'ABC', 'mala.fila@ejemplo.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 2)
        self.assertEqual(len(resumen['errores']), 1)
        self.assertTrue(Usuario.objects.filter(cedula='2000000001').exists())
        self.assertTrue(Usuario.objects.filter(cedula='2000000002').exists())
        self.assertFalse(Usuario.objects.filter(nombre='Mala Fila').exists())

    def test_el_log_de_errores_dice_la_fila_y_el_motivo(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
                self.fila('Mala Fila', 'ABC', 'mala.fila@ejemplo.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        error = respuesta.context['resumen']['errores'][0]
        self.assertEqual(error['fila'], 3)
        self.assertIn('solo dígitos', error['motivo'])
        self.assertContains(respuesta, 'solo dígitos')

    def test_el_resumen_cuenta_registrados_omitidos_y_errores(self):
        self.subir(self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')]))
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co'),
                self.fila('Mala Fila', '', 'mala.fila@ejemplo.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 1)
        self.assertEqual(resumen['omitidos'], 1)
        self.assertEqual(len(resumen['errores']), 1)
        self.assertEqual(resumen['total'], 3)

    def test_el_mensaje_final_usa_el_texto_del_brd(self):
        respuesta = self.subir(
            self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')]),
        )
        self.assertContains(respuesta, 'Se registraron 1 estudiantes')
        self.assertContains(respuesta, 'ya estaban')

    def test_una_fila_repetida_dentro_del_mismo_archivo_se_omite(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 1)
        self.assertEqual(resumen['omitidos'], 1)
        self.assertEqual(Usuario.objects.filter(cedula='2000000001').count(), 1)

    def test_una_fila_con_otra_carrera_es_un_error(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', 'Ingeniería Civil')]
        )
        respuesta = self.subir(contenido)
        errores = respuesta.context['resumen']['errores']
        self.assertEqual(len(errores), 1)
        self.assertIn('no es la que diriges', errores[0]['motivo'])
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    def test_la_carrera_tambien_se_reconoce_por_su_codigo(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', 'IS-01')]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_la_columna_carrera_vacia_asume_la_del_director(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', '')]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)
        self.assertEqual(self.inscripciones_de('ana.gil@ejemplo.edu.co').get().carrera, self.carrera)

    def test_acepta_punto_y_coma_como_separador(self):
        # Excel en Windows exporta así, y es el caso más común en la práctica.
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')],
            delimitador=';',
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_acepta_un_archivo_guardado_en_cp1252(self):
        contenido = self.csv_de(
            [self.fila('Ana Gómez Núñez', '2000000001', 'ana.gomez@ejemplo.edu.co')]
        )
        respuesta = self.subir(contenido, codificacion='cp1252')
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)
        self.assertEqual(
            Usuario.objects.get(cedula='2000000001').nombre, 'Ana Gómez Núñez'
        )

    def test_reconoce_los_encabezados_con_tilde(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')],
            columnas=['nombre', 'cédula', 'correo', 'carrera'],
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_un_archivo_sin_las_columnas_de_la_plantilla_se_rechaza_completo(self):
        contenido = self.csv_de(
            [['Ana Gil', 'ana.gil@ejemplo.edu.co']], columnas=['nombre', 'correo']
        )
        respuesta = self.subir(contenido)
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'no es un CSV con la plantilla')
        self.assertFalse(Usuario.objects.filter(rol=self.rol_estudiante).exists())

    def test_un_archivo_que_no_es_csv_se_rechaza(self):
        respuesta = self.subir('cualquier cosa', nombre='estudiantes.txt')
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'no es un CSV con la plantilla')

    def test_un_archivo_sin_filas_de_datos_se_rechaza(self):
        respuesta = self.subir(self.csv_de([]))
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'ninguna fila')

    def test_se_puede_volver_a_cargar_despues_de_un_error(self):
        self.subir(self.csv_de([], columnas=['nombre']))
        respuesta = self.subir(
            self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')])
        )
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_a_cada_estudiante_del_csv_le_llega_su_correo(self):
        mail.outbox.clear()
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co'),
            ]
        )
        self.subir(contenido)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {correo.to[0] for correo in mail.outbox},
            {'ana.gil@ejemplo.edu.co', 'beto.ruiz@ejemplo.edu.co'},
        )

    def test_el_cargue_solo_acepta_post(self):
        self.assertEqual(self.client.get(self.url_csv).status_code, 405)

    def test_sin_el_permiso_de_csv_no_se_puede_cargar(self):
        solo_uno = Rol.objects.create(nombre='Director sin CSV')
        RolPermiso.objects.create(
            rol=solo_uno, permiso=Permiso.objects.get(nombre='estudiante.registrar')
        )
        usuario = self.crear_usuario(
            'medio.director@ejemplo.edu.co', 'Medio Director', '1044444444', solo_uno
        )
        self.asignar_carrera(usuario, self.otra_carrera)
        self.client.force_login(usuario)
        respuesta = self.subir(
            self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co')])
        )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    def test_la_pantalla_no_ofrece_la_pestana_de_csv_sin_el_permiso(self):
        solo_uno = Rol.objects.create(nombre='Director sin CSV')
        RolPermiso.objects.create(
            rol=solo_uno, permiso=Permiso.objects.get(nombre='estudiante.registrar')
        )
        usuario = self.crear_usuario(
            'medio.director@ejemplo.edu.co', 'Medio Director', '1044444444', solo_uno
        )
        self.asignar_carrera(usuario, self.otra_carrera)
        self.client.force_login(usuario)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'Uno a uno')
        self.assertNotContains(respuesta, 'Archivo CSV')


class MaximoDeFilasDelCsv(BaseRegistro):
    """El límite lo configura el ADMO en SISTRA-11: aquí solo se lee."""

    def configurar(self, valor):
        return Parametro.objects.create(
            clave='registro_estudiantes.maximo_filas_csv',
            valor=valor,
            usuario_actualizacion=self.director,
        )

    def tres_filas(self):
        return self.csv_de(
            [
                ['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', ''],
                ['Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co', ''],
                ['Cira Paz', '2000000003', 'cira.paz@ejemplo.edu.co', ''],
            ]
        )

    def test_si_no_esta_configurado_no_se_limita(self):
        respuesta = self.subir(self.tres_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 3)

    def test_se_respeta_el_maximo_configurado(self):
        self.configurar('2')
        respuesta = self.subir(self.tres_filas())
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'el máximo por cargue es 2')
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    def test_un_archivo_dentro_del_maximo_pasa(self):
        self.configurar('5')
        respuesta = self.subir(self.tres_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 3)

    def test_un_valor_invalido_no_rompe_el_cargue(self):
        self.configurar('muchas')
        respuesta = self.subir(self.tres_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 3)

    def test_la_pantalla_muestra_el_maximo_cuando_esta_configurado(self):
        self.configurar('50')
        self.assertContains(self.client.get(self.url), 'Máximo 50 filas')


class ArchivosQueAntesDabanError500(BaseRegistro):
    """Lo encontró el revisor: dos entradas reales reventaban con un 500.

    Las dos vienen de archivos que un usuario de verdad puede subir, y en vez
    del log de errores (C2) devolvían una página de error.
    """

    def test_una_comilla_sin_cerrar_da_error_de_formulario_no_500(self):
        # Con una comilla suelta el lector traga el resto del archivo como un
        # solo campo y revienta al pasar el límite de tamaño de campo. Se baja
        # el límite para no tener que armar un archivo de 130 KB.
        # La comilla tiene que **abrir** el campo: una comilla en medio del
        # texto es un carácter corriente para el lector de Python.
        limite = csv.field_size_limit()
        csv.field_size_limit(50)
        try:
            contenido = self.csv_de(
                [
                    ['"Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', ''],
                    ['Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co', ''],
                    ['Cira Paz', '2000000003', 'cira.paz@ejemplo.edu.co', ''],
                ]
            )
            respuesta = self.subir(contenido)
        finally:
            csv.field_size_limit(limite)

        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'mal formado')
        self.assertContains(respuesta, 'comillas sin cerrar')

    def test_un_byte_nulo_en_el_nombre_es_una_fila_con_motivo(self):
        # Basura binaria de una exportación a medias: el NUL llegaba hasta
        # PostgreSQL, que lo rechaza, y tumbaba el cargue a mitad de camino.
        contenido = self.csv_de(
            [
                ['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', ''],
                ['Beto\x00Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co', ''],
                ['Cira Paz', '2000000003', 'cira.paz@ejemplo.edu.co', ''],
            ]
        )
        respuesta = self.subir(contenido)

        self.assertEqual(respuesta.status_code, 200)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 2)
        self.assertEqual(len(resumen['errores']), 1)
        self.assertIn('no imprimibles', resumen['errores'][0]['motivo'])
        # Las dos buenas entraron: la fila mala no tumbó el cargue.
        self.assertTrue(Usuario.objects.filter(cedula='2000000001').exists())
        self.assertTrue(Usuario.objects.filter(cedula='2000000003').exists())

    def test_un_archivo_demasiado_grande_se_rechaza_antes_de_leerlo(self):
        relleno = 'x' * (6 * 1024 * 1024)
        respuesta = self.subir(
            self.csv_de([[relleno, '2000000001', 'ana.gil@ejemplo.edu.co', '']])
        )
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'pesa más de')

    def test_la_cedula_no_acepta_digitos_que_no_son_digitos(self):
        # `'1²3'.isdigit()` y `'١٢٣'.isdigit()` dan True, y esas cédulas no
        # volverían a coincidir nunca con la real.
        for cedula in ('1²3', '١٢٣'):
            respuesta = self.registrar(cedula=cedula)
            self.assertEqual(respuesta.status_code, 200, f'pasó la cédula {cedula}')
            self.assertFalse(Usuario.objects.filter(cedula=cedula).exists())


class CuandoElCorreoNoSale(BaseRegistro):
    """Lo encontró el revisor: la pantalla afirmaba un envío que había fallado.

    Importa porque la contraseña temporal **solo** existe en ese correo: si el
    envío falla y nadie se entera, la cuenta queda creada e inservible y el
    Director la ve como registrada.
    """

    def test_el_director_se_entera_en_el_registro_uno_a_uno(self):
        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=OSError('sin servicio de correo'),
        ):
            respuesta = self.registrar(follow=True)
        self.assertContains(respuesta, 'no se pudo enviar el correo')
        self.assertContains(respuesta, 'reenviar')
        self.assertTrue(Usuario.objects.filter(cedula='1020304050').exists())

    def test_cuando_si_sale_no_se_le_avisa_de_nada(self):
        respuesta = self.registrar(follow=True)
        self.assertNotContains(respuesta, 'no se pudo enviar')

    def test_el_resumen_del_csv_cuenta_los_que_quedaron_sin_correo(self):
        contenido = self.csv_de(
            [
                ['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', ''],
                ['Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co', ''],
            ]
        )
        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=OSError('sin servicio de correo'),
        ):
            respuesta = self.subir(contenido)

        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 2)
        self.assertEqual(resumen['sin_correo'], 2)
        self.assertContains(respuesta, 'sin correo enviado')
        self.assertContains(respuesta, 'no se les pudo enviar el correo')

    def test_a_un_omitido_no_se_le_cuenta_como_sin_correo(self):
        self.subir(
            self.csv_de([['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', '']])
        )
        respuesta = self.subir(
            self.csv_de([['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', '']])
        )
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['omitidos'], 1)
        self.assertEqual(resumen['sin_correo'], 0)

    def test_el_correo_se_manda_despues_de_confirmar_la_transaccion(self):
        # Antes el envío ocurría dentro del `atomic`, así que un fallo posterior
        # dejaba al estudiante con un correo de una cuenta que se revirtió.
        enviados = []

        def espiar(*args, **kwargs):
            enviados.append(Usuario.objects.filter(cedula='1020304050').exists())
            return 1

        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail', side_effect=espiar
        ):
            self.registrar()
        # Cuando se manda el correo, la cuenta ya está confirmada en la base.
        self.assertEqual(enviados, [True])


class EstudiantesQueQuedabanAMedias(BaseRegistro):
    """Tres caminos que dejaban al estudiante registrado y sin poder hacer nada."""

    def test_una_cuenta_inactiva_no_se_inscribe_en_silencio(self):
        inactivo = self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        inactivo.estado = 'Inactivo'
        inactivo.save(update_fields=['estado'])

        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'está inactiva')
        self.assertEqual(self.inscripciones_de('laura.pena@ejemplo.edu.co').count(), 0)

    def test_una_inscripcion_sin_proceso_se_completa_al_volver_a_cargarla(self):
        # Hoy solo este módulo crea inscripciones, siempre con su proceso; pero
        # falta acordar quién más escribe en `estudiante_carrera`, y sin esto el
        # estudiante quedaría omitido para siempre y sin con qué arrancar.
        usuario = self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        estudiante = Estudiante.objects.create(usuario=usuario)
        EstudianteCarrera.objects.create(
            estudiante=estudiante, carrera=self.carrera, estado=EstadoInscripcion.ACTIVO
        )
        self.assertFalse(ProcesoTrabajoSocial.objects.exists())

        self.registrar()

        inscripcion = self.inscripciones_de('laura.pena@ejemplo.edu.co').get()
        self.assertTrue(
            ProcesoTrabajoSocial.objects.filter(estudiante_carrera=inscripcion).exists()
        )

    def test_una_inscripcion_finalizada_se_reporta_en_vez_de_omitirse(self):
        usuario = self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        estudiante = Estudiante.objects.create(usuario=usuario)
        EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=self.carrera,
            estado=EstadoInscripcion.FINALIZADO,
        )
        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Finalizado')
        self.assertContains(respuesta, 'no se puede desde aquí')


class ArreglosDeLaAuditoriaYLosPermisos(BaseRegistro):

    def test_la_auditoria_de_la_inscripcion_apunta_a_la_inscripcion(self):
        # Antes guardaba el id del usuario con tabla_afectada='estudiante_carrera',
        # así que el rastro señalaba la inscripción de otra persona.
        self.crear_usuario(
            'laura.pena@ejemplo.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        self.registrar()

        inscripcion = self.inscripciones_de('laura.pena@ejemplo.edu.co').get()
        registro = Auditoria.objects.filter(
            accion='Inscribir estudiante en carrera'
        ).latest('id_auditoria')
        self.assertEqual(registro.tabla_afectada, 'estudiante_carrera')
        self.assertEqual(registro.id_registro_afectado, inscripcion.pk)

    def test_cargar_csv_tambien_exige_el_permiso_de_registrar(self):
        # Con solo `cargar_csv` se podía hacer POST directo a la URL del archivo
        # y crear cuentas sin tener el permiso que protege el registro.
        solo_csv = Rol.objects.create(nombre='Solo CSV')
        RolPermiso.objects.create(
            rol=solo_csv, permiso=Permiso.objects.get(nombre='estudiante.cargar_csv')
        )
        usuario = self.crear_usuario(
            'solo.csv@ejemplo.edu.co', 'Solo CSV', '1033333333', solo_csv
        )
        self.asignar_carrera(usuario, self.otra_carrera)
        self.client.force_login(usuario)

        respuesta = self.subir(
            self.csv_de([['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', '']])
        )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())


class NumeroDeFilaDelLogDeErrores(BaseRegistro):
    """El número tiene que ser el del archivo, que es lo que el Director ve."""

    def test_una_linea_en_blanco_no_desalinea_la_numeracion(self):
        # `csv.DictReader` descarta las líneas vacías: contando las filas
        # devueltas, todo lo que viene después se reportaba una línea antes.
        contenido = (
            'nombre,cedula,correo,carrera\n'
            'Ana Gil,2000000001,ana.gil@ejemplo.edu.co,\n'
            '\n'
            'Mala Fila,ABC,mala.fila@ejemplo.edu.co,\n'
        )
        respuesta = self.subir(contenido)
        errores = respuesta.context['resumen']['errores']
        self.assertEqual(len(errores), 1)
        self.assertEqual(errores[0]['fila'], 4)


class ElMaximoMalConfigurado(BaseRegistro):
    """Un parámetro mal escrito no puede convertirse en un límite distinto."""

    def configurar(self, valor):
        return Parametro.objects.create(
            clave='registro_estudiantes.maximo_filas_csv',
            valor=valor,
            usuario_actualizacion=self.director,
        )

    def dos_filas(self):
        return self.csv_de(
            [
                ['Ana Gil', '2000000001', 'ana.gil@ejemplo.edu.co', ''],
                ['Beto Ruiz', '2000000002', 'beto.ruiz@ejemplo.edu.co', ''],
            ]
        )

    def test_un_guion_bajo_no_se_lee_como_numero(self):
        # `int('1_0')` da 10: el ADMO escribe «1_0» y creería tener un límite.
        self.configurar('1_0')
        respuesta = self.subir(self.dos_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)

    def test_un_valor_negativo_no_limita(self):
        self.configurar('-5')
        respuesta = self.subir(self.dos_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)

    def test_un_valor_con_espacios_se_entiende(self):
        self.configurar('  1  ')
        respuesta = self.subir(self.dos_filas())
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'el máximo por cargue es 1')

    def test_la_pantalla_dice_cuando_no_hay_maximo_configurado(self):
        self.assertContains(
            self.client.get(self.url), 'no hay un máximo de filas configurado'
        )
