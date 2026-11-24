"""SISTRA-10 · Roles (registro de estudiantes): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

import csv

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.mail import send_mail as send_mail_real
from django.core.mail.backends.locmem import EmailBackend
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad, Parametro
from apps.personas.forms.registro_estudiantes import (
    enviar_credenciales,
    maximo_de_filas_csv,
)
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
            'dora.prado@unipamplona.edu.co', 'Dora Prado', '1000000001', self.rol_director
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
            'correo': 'laura.pena@unipamplona.edu.co',
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
            'sin.permisos@unipamplona.edu.co', 'Sin Permisos', '1099999999', self.rol_estudiante
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
        inscripcion = self.inscripciones_de('laura.pena@unipamplona.edu.co').get()
        self.assertEqual(inscripcion.carrera, self.carrera)
        self.assertEqual(inscripcion.estado, EstadoInscripcion.ACTIVO)

    def test_le_crea_su_proceso_de_trabajo_social(self):
        self.registrar()
        inscripcion = self.inscripciones_de('laura.pena@unipamplona.edu.co').get()
        proceso = ProcesoTrabajoSocial.objects.get(estudiante_carrera=inscripcion)
        self.assertEqual(proceso.estado, 'Pendiente')
        self.assertIsNone(proceso.fecha_finalizacion)

    def test_le_crea_su_perfil_de_estudiante(self):
        self.registrar()
        self.assertTrue(
            Estudiante.objects.filter(
                usuario__correo_institucional='laura.pena@unipamplona.edu.co'
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
            'otro@unipamplona.edu.co', 'Otro', '1088888888', self.rol_estudiante
        )
        self.client.force_login(estudiante)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.registrar().status_code, 403)

    def test_un_director_sin_carrera_no_puede_registrar(self):
        suelto = self.crear_usuario(
            'sin.carrera@unipamplona.edu.co', 'Sin Carrera', '1077777777', self.rol_director
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
            'otra.persona@unipamplona.edu.co', 'Otra Persona', '1020304050', self.rol_estudiante
        )
        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'ya está registrada con otro correo')

    def test_el_correo_ya_usado_con_otra_cedula_se_rechaza(self):
        self.crear_usuario(
            'laura.pena@unipamplona.edu.co', 'Otra Laura', '1066666666', self.rol_estudiante
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
        self.assertEqual(self.inscripciones_de('laura.pena@unipamplona.edu.co').count(), 1)
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)

    def test_al_omitirlo_se_le_avisa_al_director(self):
        self.registrar()
        respuesta = self.client.post(
            self.url,
            {
                'nombre': 'Laura Peña',
                'cedula': '1020304050',
                'correo': 'laura.pena@unipamplona.edu.co',
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
            'luis.mora@unipamplona.edu.co', 'Luis Mora', '1055555555', self.rol_director
        )
        self.asignar_carrera(otro_director, self.otra_carrera)
        self.client.force_login(otro_director)
        self.registrar()

        self.client.force_login(self.director)
        self.registrar()

        inscripciones = self.inscripciones_de('laura.pena@unipamplona.edu.co')
        self.assertEqual(inscripciones.count(), 2)
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)
        self.assertEqual(
            set(inscripciones.values_list('carrera__nombre', flat=True)),
            {'Ingeniería de Sistemas', 'Ingeniería Civil'},
        )

    def test_cada_carrera_tiene_su_propio_proceso(self):
        otro_director = self.crear_usuario(
            'luis.mora@unipamplona.edu.co', 'Luis Mora', '1055555555', self.rol_director
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
            'luis.mora@unipamplona.edu.co', 'Luis Mora', '1055555555', self.rol_director
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
            'laura.pena@unipamplona.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        self.assertFalse(Estudiante.objects.filter(usuario=creado_por_el_admo).exists())

        self.registrar()

        self.assertTrue(Estudiante.objects.filter(usuario=creado_por_el_admo).exists())
        inscripcion = self.inscripciones_de('laura.pena@unipamplona.edu.co').get()
        self.assertEqual(inscripcion.carrera, self.carrera)
        self.assertTrue(
            ProcesoTrabajoSocial.objects.filter(estudiante_carrera=inscripcion).exists()
        )
        self.assertEqual(Usuario.objects.filter(cedula='1020304050').count(), 1)

    def test_completar_una_cuenta_queda_en_auditoria(self):
        self.crear_usuario(
            'laura.pena@unipamplona.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
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
        self.assertEqual(mail.outbox[0].to, ['laura.pena@unipamplona.edu.co'])

    def test_el_correo_lleva_el_usuario_de_ingreso_y_la_contrasena(self):
        mail.outbox.clear()
        with patch(
            'apps.personas.forms.registro_estudiantes.get_random_string',
            return_value='ClaveTemporalDePrueba',
        ):
            self.registrar()
        cuerpo = mail.outbox[0].body
        self.assertIn('laura.pena@unipamplona.edu.co', cuerpo)
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
        self.assertEqual(self.inscripciones_de('laura.pena@unipamplona.edu.co').count(), 1)


class UnaSolaConexionPorLote(BaseRegistro):
    """SIS-71 · E12 · el cargue abre una conexión de correo, no una por fila.

    `enviar_credenciales` llamaba a `send_mail` sin conexión, así que Django le
    creaba una por llamada: `connection or get_connection(...)`. Y el backend
    SMTP solo cierra la conexión **si la abrió él** (`if new_conn_created:
    self.close()`), de modo que sin un `open()` previo cada fila abría y cerraba
    la suya. Con un servidor real eso es un ida y vuelta por estudiante.
    """

    def filas_de(self, cuantas):
        return [
            [
                f'Alumno {numero}',
                f'20000{numero:05d}',
                f'alumno.{numero}@unipamplona.edu.co',
                '',
            ]
            for numero in range(1, cuantas + 1)
        ]

    def espiar_conexiones(self):
        """Cuenta cada conexión que se crea, por cualquier camino.

        Se espía `django.core.mail.get_connection` y no el nombre importado en
        mi módulo porque `send_mail` resuelve ese mismo global en cada llamada:
        así se ven tanto las conexiones que abre Django por su cuenta como la
        del lote.
        """
        from django.core import mail as modulo_de_correo

        original = modulo_de_correo.get_connection
        creadas = []

        def espia(*args, **kwargs):
            conexion = original(*args, **kwargs)
            creadas.append(conexion)
            return conexion

        return patch.object(
            modulo_de_correo, 'get_connection', side_effect=espia
        ), creadas

    def auditorias_de_envio(self):
        return Auditoria.objects.filter(accion='Enviar credenciales')

    # --- C1, C2 y C3 · cien filas, cien correos, una conexión ---

    def test_cien_filas_mandan_cien_correos_con_una_sola_conexion(self):
        espia, creadas = self.espiar_conexiones()
        with espia:
            respuesta = self.subir(self.csv_de(self.filas_de(100)))

        self.assertEqual(respuesta.context['resumen']['registrados'], 100)
        self.assertEqual(len(mail.outbox), 100)
        # Antes de E12 esto daba 100: una conexión por fila.
        self.assertEqual(len(creadas), 1)

    def test_todos_los_envios_reciben_la_misma_conexion(self):
        recibidas = []

        def espia_send_mail(*args, **kwargs):
            recibidas.append(kwargs.get('connection'))
            return send_mail_real(*args, **kwargs)

        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=espia_send_mail,
        ):
            self.subir(self.csv_de(self.filas_de(4)))

        self.assertEqual(len(recibidas), 4)
        self.assertNotIn(None, recibidas)
        self.assertEqual(len({id(c) for c in recibidas}), 1)

    # --- C4 · la conexión se abre una vez y se cierra ---

    def test_la_conexion_se_abre_una_vez_y_se_cierra(self):
        # Sin el `open()` previo, Django cerraría y reabriría en cada `send_mail`,
        # porque solo cierra la conexión que abrió él.
        with patch.object(EmailBackend, 'open', autospec=True) as abrir, \
                patch.object(EmailBackend, 'close', autospec=True) as cerrar:
            self.subir(self.csv_de(self.filas_de(4)))

        self.assertEqual(abrir.call_count, 1)
        self.assertEqual(cerrar.call_count, 1)

    def test_la_conexion_se_cierra_aunque_el_cargue_reviente(self):
        with patch.object(EmailBackend, 'close', autospec=True) as cerrar, \
                patch(
                    'apps.personas.views.registro_estudiantes.registrar_estudiante',
                    side_effect=RuntimeError('algo se rompió'),
                ):
            with self.assertRaises(RuntimeError):
                self.subir(self.csv_de(self.filas_de(2)))

        self.assertEqual(cerrar.call_count, 1)

    # --- C5 · un fallo no arrastra a los demás ---

    def test_si_un_envio_falla_los_demas_salen_y_el_fallo_queda_auditado(self):
        def falla_solo_el_segundo(*args, **kwargs):
            if 'alumno.2@unipamplona.edu.co' in kwargs['recipient_list']:
                raise OSError('ese buzón rechaza el correo')
            return send_mail_real(*args, **kwargs)

        with patch(
            'apps.personas.forms.registro_estudiantes.send_mail',
            side_effect=falla_solo_el_segundo,
        ):
            respuesta = self.subir(self.csv_de(self.filas_de(4)))

        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 4)
        self.assertEqual(resumen['sin_correo'], 1)
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(self.auditorias_de_envio().filter(resultado='Éxito').count(), 3)
        self.assertEqual(self.auditorias_de_envio().filter(resultado='Fallo').count(), 1)
        fallida = self.auditorias_de_envio().get(resultado='Fallo')
        self.assertIn('alumno.2@unipamplona.edu.co', fallida.detalle)
        # Los cuatro quedaron registrados: el correo no condiciona el registro.
        self.assertEqual(Usuario.objects.filter(rol=self.rol_estudiante).count(), 4)

    # --- C6 · servidor caído: ni un 500, ni un registro perdido ---

    def test_si_el_servidor_de_correo_esta_caido_el_cargue_no_revienta(self):
        with patch.object(
            EmailBackend, 'open', autospec=True, side_effect=OSError('servidor caído')
        ), patch.object(
            EmailBackend,
            'send_messages',
            autospec=True,
            side_effect=OSError('servidor caído'),
        ):
            respuesta = self.subir(self.csv_de(self.filas_de(3)))

        self.assertEqual(respuesta.status_code, 200)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 3)
        self.assertEqual(resumen['sin_correo'], 3)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.auditorias_de_envio().count(), 3)
        self.assertEqual(self.auditorias_de_envio().filter(resultado='Fallo').count(), 3)
        self.assertContains(respuesta, 'no se les pudo enviar el correo')

    # --- C6b · ni siquiera construir la conexión puede tumbar el cargue ---

    def test_si_la_conexion_no_se_puede_ni_construir_el_cargue_sigue(self):
        # Lo encontró la revisión: con MAILERS, `get_connection()` lanza
        # `InvalidMailer` si el .env trae `use_ssl` y `use_tls` a la vez. Antes
        # de E12 eso caía dentro del try de cada fila; si la construcción
        # quedara fuera de la guarda, serían 500 y cero estudiantes.
        from django.core import mail as modulo_de_correo

        with patch.object(
            modulo_de_correo,
            'get_connection',
            side_effect=OSError('configuración de correo inválida'),
        ):
            respuesta = self.subir(self.csv_de(self.filas_de(3)))

        self.assertEqual(respuesta.status_code, 200)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 3)
        self.assertEqual(resumen['sin_correo'], 3)
        self.assertEqual(self.auditorias_de_envio().filter(resultado='Fallo').count(), 3)
        self.assertEqual(Usuario.objects.filter(rol=self.rol_estudiante).count(), 3)

    # --- C5b · una conexión caída no arrastra a las filas siguientes ---

    def test_tras_un_envio_fallido_la_conexion_se_renueva(self):
        # Django no cierra la conexión que no abrió él, y `open()` devuelve
        # False mientras el atributo siga puesto: una conexión muerta haría
        # fallar a todas las filas siguientes. Por eso se renueva.
        def falla_solo_el_segundo(*args, **kwargs):
            if 'alumno.2@unipamplona.edu.co' in kwargs['recipient_list']:
                raise OSError('el servidor cortó la conexión')
            return send_mail_real(*args, **kwargs)

        with patch.object(EmailBackend, 'open', autospec=True) as abrir, \
                patch.object(EmailBackend, 'close', autospec=True) as cerrar, \
                patch(
                    'apps.personas.forms.registro_estudiantes.send_mail',
                    side_effect=falla_solo_el_segundo,
                ):
            respuesta = self.subir(self.csv_de(self.filas_de(4)))

        # La del lote, más la renovación tras el fallo de la segunda fila.
        self.assertEqual(abrir.call_count, 2)
        self.assertEqual(cerrar.call_count, 2)
        # Y las otras tres salieron igual.
        self.assertEqual(respuesta.context['resumen']['registrados'], 4)
        self.assertEqual(len(mail.outbox), 3)

    # --- C7 y C8 · el contrato de `enviar_credenciales` no se mueve ---

    def test_enviar_credenciales_sigue_aceptando_dos_argumentos(self):
        # Es como la llama `crear_usuario` de apps/usuarios desde SIS-69, y el
        # contrato dice que esa firma no se puede romper.
        usuario = self.crear_usuario(
            'tulio.mora@unipamplona.edu.co', 'Tulio Mora', '1000000055', self.rol_estudiante
        )
        self.assertIs(enviar_credenciales(usuario, 'ClaveDePrueba123'), True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ClaveDePrueba123', mail.outbox[0].body)

    def test_enviar_credenciales_no_lanza_con_una_conexion_rota(self):
        usuario = self.crear_usuario(
            'nidia.soto@unipamplona.edu.co', 'Nidia Soto', '1000000056', self.rol_estudiante
        )
        rota = EmailBackend()
        with patch.object(
            EmailBackend,
            'send_messages',
            autospec=True,
            side_effect=OSError('servidor caído'),
        ):
            self.assertIs(enviar_credenciales(usuario, 'ClaveDePrueba123', rota), False)
        self.assertEqual(len(mail.outbox), 0)

    def test_el_registro_uno_a_uno_sigue_mandando_su_correo(self):
        # Sin lote no hay conexión compartida: una por envío, como siempre.
        espia, creadas = self.espiar_conexiones()
        with espia:
            self.registrar()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(creadas), 1)


class CargueCsv(BaseRegistro):
    """C1 y C2 · el cargue masivo procesa fila por fila y reporta los errores."""

    def fila(self, nombre, cedula, correo, carrera='Ingeniería de Sistemas'):
        return [nombre, cedula, correo, carrera]

    def test_registra_las_filas_validas(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)
        self.assertEqual(Usuario.objects.filter(rol=self.rol_estudiante).count(), 2)

    def test_a_cada_uno_le_crea_inscripcion_y_proceso(self):
        contenido = self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')])
        self.subir(contenido)
        inscripcion = self.inscripciones_de('ana.gil@unipamplona.edu.co').get()
        self.assertEqual(inscripcion.carrera, self.carrera)
        self.assertTrue(
            ProcesoTrabajoSocial.objects.filter(estudiante_carrera=inscripcion).exists()
        )

    def test_las_filas_malas_no_tumban_las_buenas(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Mala Fila', 'ABC', 'mala.fila@unipamplona.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co'),
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
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Mala Fila', 'ABC', 'mala.fila@unipamplona.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        error = respuesta.context['resumen']['errores'][0]
        self.assertEqual(error['fila'], 3)
        self.assertIn('solo dígitos', error['motivo'])
        self.assertContains(respuesta, 'solo dígitos')

    def test_el_resumen_cuenta_registrados_omitidos_y_errores(self):
        self.subir(self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')]))
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co'),
                self.fila('Mala Fila', '', 'mala.fila@unipamplona.edu.co'),
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
            self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')]),
        )
        self.assertContains(respuesta, 'Se registraron 1 estudiantes')
        self.assertContains(respuesta, 'ya estaban')

    def test_una_fila_repetida_dentro_del_mismo_archivo_se_omite(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        resumen = respuesta.context['resumen']
        self.assertEqual(resumen['registrados'], 1)
        self.assertEqual(resumen['omitidos'], 1)
        self.assertEqual(Usuario.objects.filter(cedula='2000000001').count(), 1)

    def test_una_fila_con_otra_carrera_es_un_error(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', 'Ingeniería Civil')]
        )
        respuesta = self.subir(contenido)
        errores = respuesta.context['resumen']['errores']
        self.assertEqual(len(errores), 1)
        self.assertIn('no es la que diriges', errores[0]['motivo'])
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    def test_la_carrera_tambien_se_reconoce_por_su_codigo(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', 'IS-01')]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_la_columna_carrera_vacia_asume_la_del_director(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', '')]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)
        self.assertEqual(
            self.inscripciones_de('ana.gil@unipamplona.edu.co').get().carrera, self.carrera
        )

    def test_acepta_punto_y_coma_como_separador(self):
        # Excel en Windows exporta así, y es el caso más común en la práctica.
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')],
            delimitador=';',
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_acepta_un_archivo_guardado_en_cp1252(self):
        contenido = self.csv_de(
            [self.fila('Ana Gómez Núñez', '2000000001', 'ana.gomez@unipamplona.edu.co')]
        )
        respuesta = self.subir(contenido, codificacion='cp1252')
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)
        self.assertEqual(
            Usuario.objects.get(cedula='2000000001').nombre, 'Ana Gómez Núñez'
        )

    def test_reconoce_los_encabezados_con_tilde(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')],
            columnas=['nombre', 'cédula', 'correo', 'carrera'],
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_un_archivo_sin_las_columnas_de_la_plantilla_se_rechaza_completo(self):
        contenido = self.csv_de(
            [['Ana Gil', 'ana.gil@unipamplona.edu.co']], columnas=['nombre', 'correo']
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
            self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')])
        )
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)

    def test_a_cada_estudiante_del_csv_le_llega_su_correo(self):
        mail.outbox.clear()
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co'),
            ]
        )
        self.subir(contenido)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {correo.to[0] for correo in mail.outbox},
            {'ana.gil@unipamplona.edu.co', 'beto.ruiz@unipamplona.edu.co'},
        )

    def test_el_cargue_solo_acepta_post(self):
        self.assertEqual(self.client.get(self.url_csv).status_code, 405)

    def test_sin_el_permiso_de_csv_no_se_puede_cargar(self):
        solo_uno = Rol.objects.create(nombre='Director sin CSV')
        RolPermiso.objects.create(
            rol=solo_uno, permiso=Permiso.objects.get(nombre='estudiante.registrar')
        )
        usuario = self.crear_usuario(
            'medio.director@unipamplona.edu.co', 'Medio Director', '1044444444', solo_uno
        )
        self.asignar_carrera(usuario, self.otra_carrera)
        self.client.force_login(usuario)
        respuesta = self.subir(
            self.csv_de([self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co')])
        )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    def test_la_pantalla_no_ofrece_la_pestana_de_csv_sin_el_permiso(self):
        solo_uno = Rol.objects.create(nombre='Director sin CSV')
        RolPermiso.objects.create(
            rol=solo_uno, permiso=Permiso.objects.get(nombre='estudiante.registrar')
        )
        usuario = self.crear_usuario(
            'medio.director@unipamplona.edu.co', 'Medio Director', '1044444444', solo_uno
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
                ['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', ''],
                ['Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co', ''],
                ['Cira Paz', '2000000003', 'cira.paz@unipamplona.edu.co', ''],
            ]
        )

    def test_si_no_esta_configurado_se_aplica_el_maximo_por_defecto(self):
        # Antes de E11 no había ningún límite mientras el ADMO no guardara uno;
        # ahora rige el valor por defecto de Parametrización.
        self.assertEqual(maximo_de_filas_csv(), 100)
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

    def test_lee_el_maximo_guardado_desde_documentos_y_formatos(self):
        rol_administrador = self.rol_administrador
        permiso, _ = Permiso.objects.get_or_create(
            nombre='sistema.parametrizar',
            defaults={'descripcion': 'Acceso a parametrización', 'estado': 'Activo'},
        )
        RolPermiso.objects.get_or_create(rol=rol_administrador, permiso=permiso)
        administrador = Usuario.objects.create_user(
            correo_institucional='admin.maximo@unipamplona.edu.co',
            password='ClaveDePrueba123',
            nombre='Admin Máximo',
            cedula='1000000099',
            nombre_usuario='admin.maximo',
            rol=rol_administrador,
            requiere_cambio_contrasena=False,
        )
        self.client.force_login(administrador)

        respuesta_configuracion = self.client.post(
            reverse('parametrizacion:documentos'),
            {'max_mb_docx': '10', 'max_mb_csv': '2', 'maximo_filas_csv': '2'},
        )
        self.assertEqual(respuesta_configuracion.status_code, 302)

        self.client.force_login(self.director)
        respuesta_csv = self.subir(self.tres_filas())

        self.assertIsNone(respuesta_csv.context['resumen'])
        self.assertContains(respuesta_csv, 'el máximo por cargue es 2')
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

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
                    ['"Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', ''],
                    ['Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co', ''],
                    ['Cira Paz', '2000000003', 'cira.paz@unipamplona.edu.co', ''],
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
                ['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', ''],
                ['Beto\x00Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co', ''],
                ['Cira Paz', '2000000003', 'cira.paz@unipamplona.edu.co', ''],
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
            self.csv_de([[relleno, '2000000001', 'ana.gil@unipamplona.edu.co', '']])
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
                ['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', ''],
                ['Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co', ''],
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
            self.csv_de([['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', '']])
        )
        respuesta = self.subir(
            self.csv_de([['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', '']])
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
            'laura.pena@unipamplona.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        inactivo.estado = 'Inactivo'
        inactivo.save(update_fields=['estado'])

        respuesta = self.registrar()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'está inactiva')
        self.assertEqual(self.inscripciones_de('laura.pena@unipamplona.edu.co').count(), 0)

    def test_una_inscripcion_sin_proceso_se_completa_al_volver_a_cargarla(self):
        # Hoy solo este módulo crea inscripciones, siempre con su proceso; pero
        # falta acordar quién más escribe en `estudiante_carrera`, y sin esto el
        # estudiante quedaría omitido para siempre y sin con qué arrancar.
        usuario = self.crear_usuario(
            'laura.pena@unipamplona.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        estudiante = Estudiante.objects.create(usuario=usuario)
        EstudianteCarrera.objects.create(
            estudiante=estudiante, carrera=self.carrera, estado=EstadoInscripcion.ACTIVO
        )
        self.assertFalse(ProcesoTrabajoSocial.objects.exists())

        self.registrar()

        inscripcion = self.inscripciones_de('laura.pena@unipamplona.edu.co').get()
        self.assertTrue(
            ProcesoTrabajoSocial.objects.filter(estudiante_carrera=inscripcion).exists()
        )

    def test_una_inscripcion_finalizada_se_reporta_en_vez_de_omitirse(self):
        usuario = self.crear_usuario(
            'laura.pena@unipamplona.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
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
            'laura.pena@unipamplona.edu.co', 'Laura Peña', '1020304050', self.rol_estudiante
        )
        self.registrar()

        inscripcion = self.inscripciones_de('laura.pena@unipamplona.edu.co').get()
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
            'solo.csv@unipamplona.edu.co', 'Solo CSV', '1033333333', solo_csv
        )
        self.asignar_carrera(usuario, self.otra_carrera)
        self.client.force_login(usuario)

        respuesta = self.subir(
            self.csv_de([['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', '']])
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
            'Ana Gil,2000000001,ana.gil@unipamplona.edu.co,\n'
            '\n'
            'Mala Fila,ABC,mala.fila@unipamplona.edu.co,\n'
        )
        respuesta = self.subir(contenido)
        errores = respuesta.context['resumen']['errores']
        self.assertEqual(len(errores), 1)
        self.assertEqual(errores[0]['fila'], 4)


class LimitesDelCsvDesdeParametrizacion(BaseRegistro):
    """SIS-70 · E11 · los dos límites del cargue salen de Parametrización.

    Antes el tamaño estaba fijo en 5 MB —mientras el parámetro decía 2— y el
    máximo de filas se leía consultando la tabla `parametro` a mano, así que el
    valor por defecto de 100 no se aplicaba nunca: la tabla está vacía hasta que
    el ADMO guarda algo, y los valores iniciales viven en `servicios.py`.
    """

    def configurar(self, clave, valor):
        return Parametro.objects.create(
            clave=clave,
            valor=valor,
            usuario_actualizacion=self.director,
        )

    def filas_de(self, cuantas):
        return [
            [
                f'Alumno {numero}',
                f'20000{numero:05d}',
                f'alumno.{numero}@unipamplona.edu.co',
                '',
            ]
            for numero in range(1, cuantas + 1)
        ]

    def archivo_de_megas(self, megas):
        """Un CSV de una sola fila que pesa algo más de `megas` MB."""
        relleno = 'x' * (megas * 1024 * 1024)
        return self.csv_de(
            [[relleno, '2000000001', 'ana.gil@unipamplona.edu.co', '']]
        )

    def administrador_de_parametros(self):
        permiso, _ = Permiso.objects.get_or_create(
            nombre='sistema.parametrizar',
            defaults={'descripcion': 'Acceso a parametrización', 'estado': 'Activo'},
        )
        RolPermiso.objects.get_or_create(rol=self.rol_administrador, permiso=permiso)
        return self.crear_usuario(
            'admin.limites@unipamplona.edu.co',
            'Admin Límites',
            '1000000077',
            self.rol_administrador,
        )

    # --- C1 · el tamaño sale del parámetro, no de un 5 fijo ---

    def test_un_archivo_de_tres_megas_se_rechaza_con_los_dos_por_defecto(self):
        # Antes pasaba el control de tamaño: el límite fijo eran 5 MB.
        respuesta = self.subir(self.archivo_de_megas(3))
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'pesa más de 2 MB')

    def test_el_mensaje_del_tamano_muestra_el_valor_vigente(self):
        self.configurar('registro_estudiantes.max_mb_csv', '1')
        respuesta = self.subir(self.archivo_de_megas(2))
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'pesa más de 1 MB')

    def test_un_tamano_mas_amplio_tambien_se_respeta(self):
        self.configurar('registro_estudiantes.max_mb_csv', '10')
        # 3 MB ya no se rechazan por tamaño (la fila de relleno falla por sus
        # datos, que es otra cosa).
        respuesta = self.subir(self.archivo_de_megas(3))
        self.assertNotContains(respuesta, 'pesa más de')

    # --- C2 · el máximo de filas aplica el 100 por defecto ---

    def test_sin_parametro_guardado_el_maximo_de_filas_es_cien(self):
        self.assertEqual(maximo_de_filas_csv(), 100)

    def test_ciento_una_filas_se_rechazan_con_los_cien_por_defecto(self):
        # Antes pasaban: sin fila en `parametro` no había ningún límite.
        respuesta = self.subir(self.csv_de(self.filas_de(101)))
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'el máximo por cargue es 100')
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    # --- C4 y C5 · «con los parámetros en 1 MB y 3 filas» (la tarjeta) ---

    def test_lo_que_guarda_el_admo_en_parametrizacion_manda(self):
        self.client.force_login(self.administrador_de_parametros())
        guardado = self.client.post(
            reverse('parametrizacion:documentos'),
            {'max_mb_docx': '10', 'max_mb_csv': '1', 'maximo_filas_csv': '3'},
        )
        self.assertEqual(guardado.status_code, 302)
        self.client.force_login(self.director)

        por_tamano = self.subir(self.archivo_de_megas(2))
        self.assertIsNone(por_tamano.context['resumen'])
        self.assertContains(por_tamano, 'pesa más de 1 MB')

        por_filas = self.subir(self.csv_de(self.filas_de(4)))
        self.assertIsNone(por_filas.context['resumen'])
        self.assertContains(por_filas, 'el máximo por cargue es 3')
        self.assertFalse(Usuario.objects.filter(cedula='2000000001').exists())

    # --- C6 · la pantalla del Director muestra los dos límites ---

    def test_la_pantalla_muestra_los_dos_limites_vigentes(self):
        pantalla = self.client.get(self.url)
        self.assertContains(pantalla, 'Máximo 100 filas')
        self.assertContains(pantalla, '2 MB')

    def test_la_pantalla_sigue_los_parametros_guardados(self):
        self.configurar('registro_estudiantes.max_mb_csv', '7')
        self.configurar('registro_estudiantes.maximo_filas_csv', '30')
        pantalla = self.client.get(self.url)
        self.assertContains(pantalla, 'Máximo 30 filas')
        self.assertContains(pantalla, '7 MB')

    # --- C7 · una fila editada a mano en la base no deja el cargue inservible ---

    def test_un_tamano_de_cero_en_la_base_no_rechaza_todos_los_archivos(self):
        # Con 0 MB no entraría ni un archivo vacío: cae en el valor por defecto.
        self.configurar('registro_estudiantes.max_mb_csv', '0')
        respuesta = self.subir(self.csv_de(self.filas_de(2)))
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)
        self.assertContains(self.client.get(self.url), '2 MB')

    def test_un_tamano_no_numerico_en_la_base_cae_en_el_valor_por_defecto(self):
        self.configurar('registro_estudiantes.max_mb_csv', 'grande')
        respuesta = self.subir(self.csv_de(self.filas_de(2)))
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)
        self.assertContains(self.client.get(self.url), '2 MB')


class ElMaximoMalConfigurado(BaseRegistro):
    """Un parámetro mal escrito no puede dejar el cargue inservible.

    Desde E11 el parseo es de SISTRA-11 (`obtener_entero`) y la pantalla que los
    guarda exige un entero >= 1, así que estos valores solo llegan editando la
    fila a mano en la base. Lo que se exige aquí es que ninguno reviente. Los que
    `obtener_entero` no sabe leer caen en el valor por defecto; `'1_0'` sí lo
    sabe leer, y queda en 10: esa prueba fija el comportamiento real.
    """

    def configurar(self, valor):
        return Parametro.objects.create(
            clave='registro_estudiantes.maximo_filas_csv',
            valor=valor,
            usuario_actualizacion=self.director,
        )

    def dos_filas(self):
        return self.csv_de(
            [
                ['Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co', ''],
                ['Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co', ''],
            ]
        )

    def test_un_guion_bajo_queda_en_diez(self):
        # `int('1_0')` da 10, así que el límite queda en 10 y no en 1. No se
        # defiende aquí: la pantalla del ADMO no deja guardar «1_0», y si
        # `obtener_entero` tiene que ser más estricto se arregla en SISTRA-11,
        # para todos los módulos que lo usan. Se fija el valor, no solo que no
        # reviente: si allá lo endurecen, esta prueba se pone roja y se sabe.
        self.configurar('1_0')
        self.assertEqual(maximo_de_filas_csv(), 10)
        respuesta = self.subir(self.dos_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)

    def test_un_valor_negativo_cae_en_el_valor_por_defecto(self):
        self.configurar('-5')
        self.assertEqual(maximo_de_filas_csv(), 100)
        respuesta = self.subir(self.dos_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)

    def test_un_valor_cero_no_rechaza_todos_los_archivos(self):
        # Un límite de 0 filas dejaría el cargue inservible.
        self.configurar('0')
        self.assertEqual(maximo_de_filas_csv(), 100)
        respuesta = self.subir(self.dos_filas())
        self.assertEqual(respuesta.context['resumen']['registrados'], 2)

    def test_un_valor_con_espacios_se_entiende(self):
        self.configurar('  1  ')
        respuesta = self.subir(self.dos_filas())
        self.assertIsNone(respuesta.context['resumen'])
        self.assertContains(respuesta, 'el máximo por cargue es 1')

    def test_la_pantalla_muestra_el_maximo_por_defecto(self):
        # Ya no existe el «todavía no hay un máximo configurado»: siempre hay.
        pantalla = self.client.get(self.url)
        self.assertContains(pantalla, 'Máximo 100 filas')
        self.assertNotContains(pantalla, 'no hay un máximo de filas configurado')


class DominioInstitucionalDelCorreo(BaseRegistro):
    """SIS-42 · solo se registra con el dominio institucional.

    El login de SISTRA-13 ya exige `@unipamplona.edu.co`, y el correo es el
    usuario de ingreso (RG-14): una cuenta con otro dominio queda inservible.
    """

    def fila(self, nombre, cedula, correo, carrera='Ingeniería de Sistemas'):
        return [nombre, cedula, correo, carrera]

    def test_uno_a_uno_rechaza_un_correo_de_otro_dominio(self):
        respuesta = self.registrar(correo='laura.pena@ejemplo.edu.co')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'unipamplona.edu.co')
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_uno_a_uno_rechaza_un_dominio_que_solo_se_parece(self):
        respuesta = self.registrar(correo='laura.pena@mail.unipamplona.edu.co.co')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_uno_a_uno_acepta_el_institucional_con_mayusculas_y_espacios(self):
        respuesta = self.registrar(correo='  LAURA.PENA@UNIPAMPLONA.EDU.CO  ')
        self.assertRedirects(respuesta, self.url)
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.correo_institucional, 'laura.pena@unipamplona.edu.co')

    def test_en_el_csv_la_fila_de_otro_dominio_se_rechaza_con_su_motivo(self):
        contenido = self.csv_de(
            [
                self.fila('Ana Gil', '2000000001', 'ana.gil@unipamplona.edu.co'),
                self.fila('Mala Fila', '2000000009', 'mala.fila@ejemplo.edu.co'),
                self.fila('Beto Ruiz', '2000000002', 'beto.ruiz@unipamplona.edu.co'),
            ]
        )
        respuesta = self.subir(contenido)
        resumen = respuesta.context['resumen']
        # Las otras dos filas se procesan: una fila mala no tumba el cargue.
        self.assertEqual(resumen['registrados'], 2)
        self.assertEqual(len(resumen['errores']), 1)
        error = resumen['errores'][0]
        self.assertEqual(error['fila'], 3)
        self.assertIn('unipamplona.edu.co', error['motivo'])
        self.assertFalse(Usuario.objects.filter(cedula='2000000009').exists())
        self.assertTrue(Usuario.objects.filter(cedula='2000000001').exists())
        self.assertTrue(Usuario.objects.filter(cedula='2000000002').exists())

    def test_en_el_csv_el_institucional_con_mayusculas_y_espacios_se_registra(self):
        contenido = self.csv_de(
            [self.fila('Ana Gil', '2000000001', '  ANA.GIL@UNIPAMPLONA.EDU.CO ')]
        )
        respuesta = self.subir(contenido)
        self.assertEqual(respuesta.context['resumen']['registrados'], 1)
        self.assertTrue(self.inscripciones_de('ana.gil@unipamplona.edu.co').exists())
