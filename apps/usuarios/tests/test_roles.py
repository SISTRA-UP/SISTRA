"""SISTRA-10 · Roles (roles, permisos y usuarios): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import ProtectedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso

Usuario = get_user_model()

PERMISOS_DE_SISTRA_10 = [
    'rol.ver',
    'rol.crear',
    'rol.editar',
    'rol.inactivar',
    'rol.asignar_permisos',
    'usuario.ver',
    'usuario.inactivar',
    # Añadidos por la migración 0003, con los criterios nuevos de SIS-18.
    'usuario.crear',
    'usuario.editar',
    'usuario.eliminar',
]


class BaseRoles(TestCase):
    """Datos comunes. Los roles base y los permisos los siembra la migración 0002."""

    def setUp(self):
        self.rol_administrador = Rol.objects.get(nombre='Administrador')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.administrador = self.crear_usuario(
            'admin@ejemplo.edu.co', nombre='Ana Admin', cedula='1000000001'
        )

    def crear_usuario(self, correo, nombre='Persona de prueba', cedula='1000000000', rol=None):
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password='ClaveDePrueba123',
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=correo.split('@')[0],
            rol=rol or self.rol_administrador,
            requiere_cambio_contrasena=False,
        )

    def crear_rol_con(self, nombre, *permisos):
        """Un rol con solo esos permisos, para probar cada guarda por separado."""
        rol = Rol.objects.create(nombre=nombre)
        for permiso in Permiso.objects.filter(nombre__in=permisos):
            RolPermiso.objects.create(rol=rol, permiso=permiso)
        return rol

    def crear_carrera(self, nombre='Ingeniería Civil', codigo='IC-99'):
        facultad, _ = Facultad.objects.get_or_create(nombre='Facultad de Prueba')
        return Carrera.objects.create(facultad=facultad, nombre=nombre, codigo=codigo)

    def inscribir_en_carrera(self, usuario, nombre_carrera, codigo_carrera):
        """Deja al usuario como estudiante inscrito en una carrera."""
        carrera = self.crear_carrera(nombre_carrera, codigo_carrera)
        estudiante = Estudiante.objects.create(usuario=usuario)
        return EstudianteCarrera.objects.create(
            estudiante=estudiante, carrera=carrera, estado=EstadoInscripcion.ACTIVO
        )


class SiembraDeRolesYPermisos(BaseRoles):
    """C0 · base para el resto: sin permisos sembrados no hay nada que asignar."""

    def test_existen_los_tres_roles_iniciales(self):
        # Regla de negocio §3.6: Estudiante, Director y Administrador.
        nombres = set(Rol.objects.values_list('nombre', flat=True))
        self.assertTrue({'Estudiante', 'Director', 'Administrador'}.issubset(nombres))

    def test_existe_el_catalogo_de_permisos_de_sistra_10(self):
        sembrados = set(Permiso.objects.values_list('nombre', flat=True))
        self.assertTrue(set(PERMISOS_DE_SISTRA_10).issubset(sembrados))

    def test_el_administrador_tiene_todos_los_permisos_de_sistra_10(self):
        for nombre in PERMISOS_DE_SISTRA_10:
            with self.subTest(permiso=nombre):
                self.assertTrue(self.administrador.has_perm(nombre))

    def test_el_estudiante_no_tiene_permisos_de_administracion(self):
        estudiante = self.crear_usuario(
            'pedro.perez@ejemplo.edu.co', cedula='1000000002', rol=self.rol_estudiante
        )
        self.assertFalse(estudiante.has_perm('rol.crear'))
        self.assertFalse(estudiante.has_perm('usuario.ver'))


class CrearRolConPermisos(BaseRoles):
    """C1 · El ADMO puede crear un rol y asignarle permisos; al recargar se conservan."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)

    def test_crea_el_rol_con_los_permisos_marcados(self):
        permisos = Permiso.objects.filter(nombre__in=['rol.ver', 'usuario.ver'])
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Secretaria',
                'descripcion': 'Consulta roles y usuarios',
                'estado': Estado.ACTIVO,
                'permisos': [p.pk for p in permisos],
            },
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))

        rol = Rol.objects.get(nombre='Secretaria')
        guardados = set(
            RolPermiso.objects.filter(rol=rol).values_list('permiso__nombre', flat=True)
        )
        self.assertEqual(guardados, {'rol.ver', 'usuario.ver'})

    def test_los_permisos_se_conservan_al_recargar_la_pantalla(self):
        permisos = Permiso.objects.filter(nombre__in=['rol.ver', 'usuario.ver'])
        self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Secretaria',
                'descripcion': '',
                'estado': Estado.ACTIVO,
                'permisos': [p.pk for p in permisos],
            },
        )
        rol = Rol.objects.get(nombre='Secretaria')

        # "Al guardar y recargar se conservan": se vuelve a pedir la pantalla de edición
        # y los permisos tienen que llegar marcados.
        respuesta = self.client.get(reverse('usuarios:rol_editar', args=[rol.pk]))
        self.assertEqual(respuesta.status_code, 200)
        marcados = set(respuesta.context['formulario']['permisos'].initial)
        self.assertEqual(marcados, {p.pk for p in permisos})

    def test_al_editar_se_quitan_los_permisos_desmarcados(self):
        rol = Rol.objects.create(nombre='Secretaria')
        todos = list(Permiso.objects.filter(nombre__in=['rol.ver', 'usuario.ver']))
        for permiso in todos:
            RolPermiso.objects.create(rol=rol, permiso=permiso)

        self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {
                'nombre': 'Secretaria',
                'descripcion': '',
                'estado': Estado.ACTIVO,
                'permisos': [todos[0].pk],
            },
        )
        guardados = set(RolPermiso.objects.filter(rol=rol).values_list('permiso_id', flat=True))
        self.assertEqual(guardados, {todos[0].pk})

    def test_no_se_repite_el_nombre_del_rol(self):
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {'nombre': 'Administrador', 'descripcion': '', 'estado': Estado.ACTIVO},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Rol.objects.filter(nombre='Administrador').count(), 1)

    def test_inactivar_un_rol_le_quita_los_permisos_a_sus_usuarios(self):
        rol = Rol.objects.create(nombre='Secretaria')
        RolPermiso.objects.create(rol=rol, permiso=Permiso.objects.get(nombre='rol.ver'))
        secretaria = self.crear_usuario(
            'sara.soto@ejemplo.edu.co', cedula='1000000003', rol=rol
        )
        self.assertTrue(secretaria.has_perm('rol.ver'))

        respuesta = self.client.post(reverse('usuarios:rol_estado', args=[rol.pk]))
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        rol.refresh_from_db()
        self.assertEqual(rol.estado, Estado.INACTIVO)

        # El modelo memoriza los permisos por instancia: se vuelve a leer de la base.
        self.assertFalse(Usuario.objects.get(pk=secretaria.pk).has_perm('rol.ver'))

    def test_sin_permiso_no_se_puede_crear_un_rol(self):
        self.client.force_login(
            self.crear_usuario(
                'luis.lopez@ejemplo.edu.co', cedula='1000000004', rol=self.rol_estudiante
            )
        )
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {'nombre': 'Intruso', 'descripcion': '', 'estado': Estado.ACTIVO},
        )
        self.assertEqual(respuesta.status_code, 403)
        self.assertFalse(Rol.objects.filter(nombre='Intruso').exists())

    def test_la_pantalla_lista_los_roles_con_su_total_de_permisos(self):
        respuesta = self.client.get(reverse('usuarios:roles'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Administrador')
        self.assertContains(respuesta, 'Estudiante')
        administrador = next(
            rol for rol in respuesta.context['roles'] if rol.nombre == 'Administrador'
        )
        # >= porque otros tickets (SISTRA-11, etc.) siembran permisos adicionales
        self.assertGreaterEqual(administrador.total_permisos, len(PERMISOS_DE_SISTRA_10))

    def test_quien_no_ha_entrado_no_ve_los_roles(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('usuarios:roles')).status_code, 403)

    def test_con_rol_editar_pero_sin_rol_inactivar_no_se_cambia_el_estado(self):
        # `estado` no es campo del formulario a propósito: si lo fuera, este POST
        # inactivaría el rol sin tener `rol.inactivar`.
        editor = self.crear_rol_con('Editor', 'rol.ver', 'rol.editar')
        self.client.force_login(
            self.crear_usuario('eva.editora@ejemplo.edu.co', cedula='1000000011', rol=editor)
        )
        objetivo = Rol.objects.create(nombre='Secretaria')

        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[objetivo.pk]),
            {'nombre': 'Secretaria', 'descripcion': '', 'estado': Estado.INACTIVO},
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        objetivo.refresh_from_db()
        self.assertEqual(objetivo.estado, Estado.ACTIVO)

        # Y la vista dedicada sí le pide el permiso que no tiene.
        self.assertEqual(
            self.client.post(reverse('usuarios:rol_estado', args=[objetivo.pk])).status_code,
            403,
        )

    def test_sin_el_permiso_de_asignar_no_se_pueden_inyectar_permisos(self):
        creador = self.crear_rol_con('Creador', 'rol.ver', 'rol.crear')
        self.client.force_login(
            self.crear_usuario('caro.creadora@ejemplo.edu.co', cedula='1000000012', rol=creador)
        )
        respuesta = self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Secretaria',
                'descripcion': '',
                'permisos': [Permiso.objects.get(nombre='usuario.inactivar').pk],
            },
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        rol = Rol.objects.get(nombre='Secretaria')
        self.assertEqual(RolPermiso.objects.filter(rol=rol).count(), 0)

    def test_no_se_puede_inactivar_un_rol_base(self):
        # Inactivar `Administrador` le quitaría los permisos a todos los
        # administradores, incluido el de reactivarlo: el sistema queda sin salida.
        for nombre in ['Administrador', 'Director', 'Estudiante']:
            with self.subTest(rol=nombre):
                rol = Rol.objects.get(nombre=nombre)
                respuesta = self.client.post(reverse('usuarios:rol_estado', args=[rol.pk]))
                self.assertRedirects(respuesta, reverse('usuarios:roles'))
                rol.refresh_from_db()
                self.assertEqual(rol.estado, Estado.ACTIVO)
        self.assertTrue(
            Usuario.objects.get(pk=self.administrador.pk).has_perm('rol.inactivar')
        )

    def test_no_se_puede_renombrar_un_rol_base(self):
        # Renombrar `Administrador` rompería `Usuario.es_administrador` en silencio.
        rol = Rol.objects.get(nombre='Administrador')
        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {'nombre': 'Admin', 'descripcion': 'cambiado'},
        )
        self.assertEqual(respuesta.status_code, 200)
        rol.refresh_from_db()
        self.assertEqual(rol.nombre, 'Administrador')

    def test_a_un_rol_base_si_se_le_cambian_los_permisos(self):
        rol = Rol.objects.get(nombre='Director')
        permiso = Permiso.objects.get(nombre='usuario.ver')
        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {'nombre': 'Director', 'descripcion': 'Director de carrera', 'permisos': [permiso.pk]},
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        self.assertEqual(
            set(RolPermiso.objects.filter(rol=rol).values_list('permiso__nombre', flat=True)),
            {'usuario.ver'},
        )

    def test_la_pantalla_no_ofrece_inactivar_los_roles_base(self):
        respuesta = self.client.get(reverse('usuarios:roles'))
        base = {rol.nombre for rol in respuesta.context['roles'] if rol.es_base}
        self.assertEqual(base, {'Estudiante', 'Director', 'Administrador'})


class BuscarYFiltrarUsuarios(BaseRoles):
    """C2 · La búsqueda encuentra por nombre, código o carrera, y el filtro por rol funciona."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.estudiante = self.crear_usuario(
            'maria.gomez@ejemplo.edu.co',
            nombre='María Gómez',
            cedula='1098765432',
            rol=self.rol_estudiante,
        )
        self.inscribir_en_carrera(self.estudiante, 'Ingeniería de Sistemas', 'IS-01')

    def buscar(self, **parametros):
        respuesta = self.client.get(reverse('usuarios:usuarios'), parametros)
        self.assertEqual(respuesta.status_code, 200)
        return list(respuesta.context['usuarios'])

    def test_busca_por_nombre(self):
        self.assertEqual(self.buscar(q='María'), [self.estudiante])

    def test_busca_sin_tildes_si_coincide_el_nombre_de_usuario(self):
        # 'Maria' no coincide con 'María' en el nombre, pero sí con 'maria.gomez'.
        self.assertEqual(self.buscar(q='Maria'), [self.estudiante])

    def test_la_busqueda_por_nombre_no_ignora_las_tildes(self):
        # Limitación conocida: `icontains` sobre PostgreSQL no normaliza tildes.
        # Queda anotada en DUDAS; se resolvería con la extensión `unaccent`.
        nunez = self.crear_usuario(
            'pedro.p@ejemplo.edu.co',
            nombre='Pedro Núñez',
            cedula='1000000055',
            rol=self.rol_estudiante,
        )
        self.assertEqual(self.buscar(q='Nunez'), [])
        self.assertEqual(self.buscar(q='Núñez'), [nunez])

    def test_busca_por_cedula(self):
        self.assertEqual(self.buscar(q='1098765432'), [self.estudiante])

    def test_busca_por_nombre_de_usuario(self):
        self.assertEqual(self.buscar(q='maria.gomez'), [self.estudiante])

    def test_busca_por_correo_institucional(self):
        self.assertEqual(self.buscar(q='maria.gomez@ejemplo.edu.co'), [self.estudiante])

    def test_busca_por_nombre_de_la_carrera(self):
        self.assertEqual(self.buscar(q='Ingeniería de Sistemas'), [self.estudiante])

    def test_busca_por_codigo_de_la_carrera(self):
        self.assertEqual(self.buscar(q='IS-01'), [self.estudiante])

    def test_no_repite_al_estudiante_inscrito_en_dos_carreras(self):
        facultad = Facultad.objects.get(nombre='Facultad de Prueba')
        segunda = Carrera.objects.create(
            facultad=facultad, nombre='Ingeniería Civil', codigo='IC-01'
        )
        EstudianteCarrera.objects.create(
            estudiante=self.estudiante.estudiante,
            carrera=segunda,
            estado=EstadoInscripcion.ACTIVO,
        )
        self.assertEqual(self.buscar(q='Ingeniería'), [self.estudiante])

    def test_filtra_por_rol(self):
        self.assertEqual(self.buscar(rol=self.rol_estudiante.pk), [self.estudiante])
        self.assertEqual(self.buscar(rol=self.rol_administrador.pk), [self.administrador])

    def test_la_busqueda_y_el_filtro_se_combinan(self):
        self.assertEqual(self.buscar(q='María', rol=self.rol_administrador.pk), [])

    def test_sin_criterios_muestra_todos(self):
        self.assertCountEqual(self.buscar(), [self.administrador, self.estudiante])

    def test_sin_permiso_no_se_ve_la_lista(self):
        self.client.force_login(self.estudiante)
        self.assertEqual(self.client.get(reverse('usuarios:usuarios')).status_code, 403)


class InactivarUsuarios(BaseRoles):
    """C3 · Un usuario con trámites no se puede eliminar, solo inactivar."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.estudiante = self.crear_usuario(
            'juan.ruiz@ejemplo.edu.co',
            nombre='Juan Ruiz',
            cedula='1012345678',
            rol=self.rol_estudiante,
        )
        self.inscripcion = self.inscribir_en_carrera(
            self.estudiante, 'Ingeniería de Sistemas', 'IS-01'
        )

    def crear_tramite(self):
        return ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.PENDIENTE,
        )

    def test_inactivar_deja_al_usuario_sin_acceso(self):
        self.crear_tramite()
        respuesta = self.client.post(
            reverse('usuarios:usuario_estado', args=[self.estudiante.pk])
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))

        self.estudiante.refresh_from_db()
        self.assertEqual(self.estudiante.estado, Estado.INACTIVO)
        self.assertFalse(self.estudiante.is_active)

    def test_se_puede_reactivar(self):
        self.estudiante.estado = Estado.INACTIVO
        self.estudiante.save(update_fields=['estado'])
        self.client.post(reverse('usuarios:usuario_estado', args=[self.estudiante.pk]))

        self.estudiante.refresh_from_db()
        self.assertEqual(self.estudiante.estado, Estado.ACTIVO)
        self.assertTrue(self.estudiante.is_active)

    def test_inactivar_no_borra_el_tramite(self):
        proceso = self.crear_tramite()
        self.client.post(reverse('usuarios:usuario_estado', args=[self.estudiante.pk]))
        self.assertTrue(ProcesoTrabajoSocial.objects.filter(pk=proceso.pk).exists())

    def test_la_pantalla_ofrece_inactivar(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Inactivar')

    def test_un_usuario_con_tramites_no_se_puede_eliminar(self):
        self.crear_tramite()
        with self.assertRaises(ProtectedError):
            self.estudiante.delete()
        self.assertTrue(Usuario.objects.filter(pk=self.estudiante.pk).exists())

    def test_sin_permiso_no_se_puede_inactivar(self):
        self.client.force_login(self.estudiante)
        respuesta = self.client.post(
            reverse('usuarios:usuario_estado', args=[self.administrador.pk])
        )
        self.assertEqual(respuesta.status_code, 403)
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.estado, Estado.ACTIVO)

    def test_el_administrador_no_se_puede_inactivar_a_si_mismo(self):
        respuesta = self.client.post(
            reverse('usuarios:usuario_estado', args=[self.administrador.pk])
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.estado, Estado.ACTIVO)


class CrearUsuarios(BaseRoles):
    """C5 · El ADMO crea usuarios; a los Directores les asigna su carrera."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.carrera = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')

    def datos(self, **cambios):
        datos = {
            'nombre': 'Laura Peña',
            'cedula': '1020304050',
            'correo_institucional': 'laura.pena@ejemplo.edu.co',
            'rol': self.rol_estudiante.pk,
            'carrera': '',
        }
        datos.update(cambios)
        return datos

    def crear(self, **cambios):
        return self.client.post(reverse('usuarios:usuario_nuevo'), self.datos(**cambios))

    def test_crea_el_usuario_con_sus_datos(self):
        respuesta = self.crear()
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre, 'Laura Peña')
        self.assertEqual(usuario.correo_institucional, 'laura.pena@ejemplo.edu.co')
        self.assertEqual(usuario.rol, self.rol_estudiante)
        self.assertEqual(usuario.estado, Estado.ACTIVO)

    def test_el_nombre_de_usuario_sale_del_correo(self):
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre_usuario, 'laura.pena')

    def test_si_el_nombre_de_usuario_ya_existe_se_le_agrega_un_numero(self):
        self.crear_usuario(
            'laura.pena@otrodominio.edu.co', nombre='Laura Homónima', cedula='9999999999'
        )
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertEqual(usuario.nombre_usuario, 'laura.pena-2')

    def test_la_contrasena_queda_temporal_y_cifrada(self):
        self.crear()
        usuario = Usuario.objects.get(cedula='1020304050')
        self.assertTrue(usuario.requiere_cambio_contrasena)
        # Guardada como hash de Django, nunca en texto plano (RG-12 / SEC-01).
        self.assertTrue(usuario.password.startswith('pbkdf2_'))

    def test_la_contrasena_temporal_no_se_muestra_en_pantalla(self):
        with patch(
            'apps.usuarios.forms.roles.get_random_string',
            return_value='ClaveTemporalDePrueba',
        ):
            respuesta = self.crear()
        seguir = self.client.get(respuesta.url)
        self.assertNotContains(seguir, 'ClaveTemporalDePrueba')

    def test_al_crear_un_director_se_le_asigna_su_carrera(self):
        respuesta = self.crear(rol=self.rol_director.pk, carrera=self.carrera.pk)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        usuario = Usuario.objects.get(cedula='1020304050')
        asignacion = DirectorCarrera.objects.get(director__usuario=usuario)
        self.assertEqual(asignacion.carrera, self.carrera)
        self.assertTrue(asignacion.activo)
        self.assertIsNone(asignacion.fecha_fin)

    def test_un_director_sin_carrera_no_se_crea(self):
        respuesta = self.crear(rol=self.rol_director.pk, carrera='')
        self.assertEqual(respuesta.status_code, 200)
        self.assertFormError(
            respuesta.context['formulario'],
            'carrera',
            'Un Director necesita la carrera que va a dirigir.',
        )
        self.assertFalse(Usuario.objects.filter(cedula='1020304050').exists())

    def test_una_carrera_no_puede_tener_dos_directores_activos(self):
        self.crear(rol=self.rol_director.pk, carrera=self.carrera.pk)
        respuesta = self.crear(
            nombre='Otro Director',
            cedula='2020202020',
            correo_institucional='otro.director@ejemplo.edu.co',
            rol=self.rol_director.pk,
            carrera=self.carrera.pk,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            DirectorCarrera.objects.filter(carrera=self.carrera, activo=True).count(), 1
        )
        self.assertFalse(Usuario.objects.filter(cedula='2020202020').exists())

    def test_la_carrera_solo_se_le_asigna_a_un_director(self):
        respuesta = self.crear(rol=self.rol_estudiante.pk, carrera=self.carrera.pk)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFormError(
            respuesta.context['formulario'],
            'carrera',
            'La carrera solo se le asigna a un Director.',
        )

    def test_no_se_repite_la_cedula(self):
        respuesta = self.crear(cedula=self.administrador.cedula)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.filter(nombre='Laura Peña').exists())

    def test_el_formulario_no_pide_el_estado_ni_la_contrasena(self):
        respuesta = self.client.get(reverse('usuarios:usuario_nuevo'))
        campos = set(respuesta.context['formulario'].fields)
        self.assertEqual(
            campos, {'nombre', 'cedula', 'correo_institucional', 'rol', 'carrera'}
        )

    def test_sin_el_permiso_no_se_puede_crear(self):
        miron = self.crear_usuario(
            'solo.mira@ejemplo.edu.co',
            nombre='Solo Mira',
            cedula='3030303030',
            rol=self.crear_rol_con('Consulta', 'usuario.ver'),
        )
        self.client.force_login(miron)
        self.assertEqual(self.crear().status_code, 403)
        self.assertEqual(
            self.client.get(reverse('usuarios:usuario_nuevo')).status_code, 403
        )

    def test_la_pantalla_ofrece_el_boton_de_nuevo_usuario(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertContains(respuesta, reverse('usuarios:usuario_nuevo'))


class EditarUsuarios(BaseRoles):
    """C6 · El ADMO edita los datos de un usuario y le cambia el rol."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.sistemas = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')
        self.civil = self.crear_carrera('Ingeniería Civil', 'IC-01')
        self.usuario = self.crear_usuario(
            'pedro.diaz@ejemplo.edu.co',
            nombre='Pedro Díaz',
            cedula='1055555555',
            rol=self.rol_estudiante,
        )

    def editar(self, usuario, **cambios):
        datos = {
            'nombre': usuario.nombre,
            'cedula': usuario.cedula,
            'correo_institucional': usuario.correo_institucional,
            'rol': usuario.rol_id,
            'carrera': '',
        }
        datos.update(cambios)
        return self.client.post(
            reverse('usuarios:usuario_editar', args=[usuario.pk]), datos
        )

    def hacer_director(self, usuario, carrera):
        self.editar(usuario, rol=self.rol_director.pk, carrera=carrera.pk)
        usuario.refresh_from_db()
        return usuario

    def test_cambia_los_datos(self):
        respuesta = self.editar(self.usuario, nombre='Pedro Díaz Mora')
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre, 'Pedro Díaz Mora')

    def test_cambia_el_rol(self):
        self.editar(self.usuario, rol=self.rol_administrador.pk)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.rol, self.rol_administrador)

    def test_al_volverlo_director_se_le_crea_el_perfil_y_la_asignacion(self):
        self.hacer_director(self.usuario, self.sistemas)
        self.assertTrue(Director.objects.filter(usuario=self.usuario).exists())
        asignacion = DirectorCarrera.objects.get(director__usuario=self.usuario)
        self.assertEqual(asignacion.carrera, self.sistemas)
        self.assertTrue(asignacion.activo)

    def test_cambiarle_la_carrera_cierra_la_anterior_y_abre_la_nueva(self):
        self.hacer_director(self.usuario, self.sistemas)
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.civil.pk)

        anterior = DirectorCarrera.objects.get(
            director__usuario=self.usuario, carrera=self.sistemas
        )
        self.assertFalse(anterior.activo)
        self.assertIsNotNone(anterior.fecha_fin)

        nueva = DirectorCarrera.objects.get(
            director__usuario=self.usuario, carrera=self.civil
        )
        self.assertTrue(nueva.activo)
        # La carrera anterior queda libre para otro Director.
        self.assertFalse(
            DirectorCarrera.objects.filter(carrera=self.sistemas, activo=True).exists()
        )

    def test_quitarle_el_rol_de_director_cierra_su_asignacion_sin_borrarla(self):
        self.hacer_director(self.usuario, self.sistemas)
        self.editar(self.usuario, rol=self.rol_estudiante.pk, carrera='')

        asignacion = DirectorCarrera.objects.get(director__usuario=self.usuario)
        self.assertFalse(asignacion.activo)
        self.assertIsNotNone(asignacion.fecha_fin)
        # El historial se conserva (regla §17): la fila sigue ahí.
        self.assertEqual(DirectorCarrera.objects.count(), 1)

    def test_no_puede_cambiarse_el_rol_a_si_mismo(self):
        respuesta = self.editar(self.administrador, rol=self.rol_estudiante.pk)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.rol, self.rol_administrador)

    def test_si_puede_cambiarse_sus_propios_datos(self):
        self.editar(self.administrador, nombre='Ana Admin Mora')
        self.administrador.refresh_from_db()
        self.assertEqual(self.administrador.nombre, 'Ana Admin Mora')

    def test_con_usuario_editar_pero_sin_usuario_inactivar_no_se_cambia_el_estado(self):
        editor = self.crear_usuario(
            'editor@ejemplo.edu.co',
            nombre='Solo Edita',
            cedula='4040404040',
            rol=self.crear_rol_con('Edición', 'usuario.ver', 'usuario.editar'),
        )
        self.client.force_login(editor)
        self.client.post(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk]),
            {
                'nombre': self.usuario.nombre,
                'cedula': self.usuario.cedula,
                'correo_institucional': self.usuario.correo_institucional,
                'rol': self.usuario.rol_id,
                'carrera': '',
                'estado': Estado.INACTIVO,
            },
        )
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.estado, Estado.ACTIVO)

    def test_sin_el_permiso_no_se_puede_editar(self):
        self.client.force_login(self.usuario)
        respuesta = self.editar(self.usuario, nombre='Me Edito Solo')
        self.assertEqual(respuesta.status_code, 403)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre, 'Pedro Díaz')


class EliminarUsuarios(BaseRoles):
    """C8 · Se elimina un usuario que no tenga nada registrado; los demás se inactivan.

    La profesora fijó que ningún estudiante se borra, solo se deshabilita. Eso
    lo garantiza la base: todo lo que apunta a `usuario` es ON DELETE RESTRICT.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.suelto = self.crear_usuario(
            'creado.por.error@ejemplo.edu.co',
            nombre='Creado Por Error',
            cedula='1066666666',
            rol=self.rol_estudiante,
        )
        self.estudiante = self.crear_usuario(
            'sofia.lara@ejemplo.edu.co',
            nombre='Sofía Lara',
            cedula='1077777777',
            rol=self.rol_estudiante,
        )
        self.inscripcion = self.inscribir_en_carrera(
            self.estudiante, 'Ingeniería de Sistemas', 'IS-01'
        )

    def eliminar(self, usuario):
        return self.client.post(reverse('usuarios:usuario_eliminar', args=[usuario.pk]))

    def test_un_usuario_sin_nada_registrado_si_se_elimina(self):
        respuesta = self.eliminar(self.suelto)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.assertFalse(Usuario.objects.filter(cedula='1066666666').exists())

    def test_un_estudiante_no_se_elimina_aunque_no_tenga_tramites(self):
        # Lo protege su propia fila en `estudiante`: la regla de la profesora.
        respuesta = self.eliminar(self.estudiante)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.assertTrue(Usuario.objects.filter(pk=self.estudiante.pk).exists())

    def test_un_estudiante_con_tramites_tampoco_se_elimina(self):
        ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.PENDIENTE,
        )
        self.eliminar(self.estudiante)
        self.assertTrue(Usuario.objects.filter(pk=self.estudiante.pk).exists())
        self.assertTrue(ProcesoTrabajoSocial.objects.exists())

    def test_cuando_no_se_puede_eliminar_se_ofrece_inactivar(self):
        respuesta = self.client.post(
            reverse('usuarios:usuario_eliminar', args=[self.estudiante.pk]), follow=True
        )
        self.assertContains(respuesta, 'no se puede')
        self.assertContains(respuesta, 'inactivarlo')

    def test_un_director_no_se_elimina(self):
        director = Director.objects.create(usuario=self.suelto)
        DirectorCarrera.objects.create(
            director=director,
            carrera=self.crear_carrera('Ingeniería Civil', 'IC-01'),
            fecha_inicio=timezone.localdate(),
        )
        self.eliminar(self.suelto)
        self.assertTrue(Usuario.objects.filter(pk=self.suelto.pk).exists())

    def test_no_puede_eliminar_su_propia_cuenta(self):
        respuesta = self.eliminar(self.administrador)
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.assertTrue(Usuario.objects.filter(pk=self.administrador.pk).exists())

    def test_eliminar_solo_acepta_post(self):
        respuesta = self.client.get(
            reverse('usuarios:usuario_eliminar', args=[self.suelto.pk])
        )
        self.assertEqual(respuesta.status_code, 405)
        self.assertTrue(Usuario.objects.filter(pk=self.suelto.pk).exists())

    def test_sin_el_permiso_no_se_puede_eliminar(self):
        self.client.force_login(self.estudiante)
        respuesta = self.eliminar(self.suelto)
        self.assertEqual(respuesta.status_code, 403)
        self.assertTrue(Usuario.objects.filter(pk=self.suelto.pk).exists())


class AuditoriaDeLosCambios(BaseRoles):
    """C10 · Todo cambio de usuarios, roles y permisos queda en `auditoria`."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.usuario = self.crear_usuario(
            'ruth.vega@ejemplo.edu.co',
            nombre='Ruth Vega',
            cedula='1088888888',
            rol=self.rol_estudiante,
        )

    def ultima(self):
        return Auditoria.objects.latest('id_auditoria')

    def test_crear_un_usuario_queda_registrado(self):
        self.client.post(
            reverse('usuarios:usuario_nuevo'),
            {
                'nombre': 'Hugo Mena',
                'cedula': '1099999999',
                'correo_institucional': 'hugo.mena@ejemplo.edu.co',
                'rol': self.rol_estudiante.pk,
                'carrera': '',
            },
        )
        creado = Usuario.objects.get(cedula='1099999999')
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Crear usuario')
        self.assertEqual(registro.tabla_afectada, 'usuario')
        self.assertEqual(registro.id_registro_afectado, creado.pk)
        self.assertEqual(registro.resultado, 'Éxito')
        self.assertIn('Hugo Mena', registro.detalle)

    def test_la_auditoria_guarda_quien_lo_hizo_y_cuando(self):
        antes = timezone.now()
        self.client.post(reverse('usuarios:usuario_estado', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.usuario, self.administrador)
        self.assertGreaterEqual(registro.fecha_hora, antes)

    def test_editar_guarda_el_valor_anterior_y_el_nuevo(self):
        self.client.post(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk]),
            {
                'nombre': 'Ruth Vega Ariza',
                'cedula': self.usuario.cedula,
                'correo_institucional': self.usuario.correo_institucional,
                'rol': self.rol_administrador.pk,
                'carrera': '',
            },
        )
        detalle = self.ultima().detalle
        self.assertIn('nombre: Ruth Vega → Ruth Vega Ariza', detalle)
        self.assertIn('rol: Estudiante → Administrador', detalle)

    def test_cambiar_el_estado_queda_registrado_con_el_antes_y_el_despues(self):
        self.client.post(reverse('usuarios:usuario_estado', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Cambiar estado de usuario')
        self.assertIn('estado: Activo → Inactivo', registro.detalle)

    def test_eliminar_queda_registrado_con_los_datos_del_usuario(self):
        self.client.post(reverse('usuarios:usuario_eliminar', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Eliminar usuario')
        self.assertEqual(registro.resultado, 'Éxito')
        self.assertIn('ruth.vega@ejemplo.edu.co', registro.detalle)

    def test_un_borrado_que_falla_tambien_queda_registrado(self):
        self.inscribir_en_carrera(self.usuario, 'Ingeniería de Sistemas', 'IS-01')
        self.client.post(reverse('usuarios:usuario_eliminar', args=[self.usuario.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Eliminar usuario')
        self.assertEqual(registro.resultado, 'Fallo')

    def test_la_auditoria_no_impide_eliminar_al_usuario_auditado(self):
        # `auditoria.id_usuario` es quien HIZO la acción; a quién se le hizo va
        # en `id_registro_afectado`, que no es clave foránea.
        self.client.post(reverse('usuarios:usuario_estado', args=[self.usuario.pk]))
        self.assertTrue(
            Auditoria.objects.filter(id_registro_afectado=self.usuario.pk).exists()
        )
        self.client.post(reverse('usuarios:usuario_eliminar', args=[self.usuario.pk]))
        self.assertFalse(Usuario.objects.filter(cedula='1088888888').exists())
        self.assertTrue(
            Auditoria.objects.filter(id_registro_afectado=self.usuario.pk).exists()
        )

    def test_crear_un_rol_con_permisos_queda_registrado(self):
        self.client.post(
            reverse('usuarios:rol_nuevo'),
            {
                'nombre': 'Auditor',
                'descripcion': 'Solo consulta.',
                'permisos': [Permiso.objects.get(nombre='usuario.ver').pk],
            },
        )
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Crear rol')
        self.assertEqual(registro.tabla_afectada, 'rol')
        self.assertIn('permisos +[usuario.ver]', registro.detalle)

    def test_quitarle_un_permiso_a_un_rol_queda_registrado(self):
        rol = self.crear_rol_con('Auditor', 'usuario.ver', 'rol.ver')
        self.client.post(
            reverse('usuarios:rol_editar', args=[rol.pk]),
            {
                'nombre': rol.nombre,
                'descripcion': '',
                'permisos': [Permiso.objects.get(nombre='rol.ver').pk],
            },
        )
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Editar rol')
        self.assertIn('permisos -[usuario.ver]', registro.detalle)

    def test_cambiar_el_estado_de_un_rol_queda_registrado(self):
        rol = self.crear_rol_con('Auditor', 'usuario.ver')
        self.client.post(reverse('usuarios:rol_estado', args=[rol.pk]))
        registro = self.ultima()
        self.assertEqual(registro.accion, 'Cambiar estado de rol')
        self.assertIn('estado: Activo → Inactivo', registro.detalle)


class ColumnaCarreraEnLaLista(BaseRoles):
    """C9 · La lista de usuarios muestra Nombre, Cédula, Correo, Carrera, Rol y Estado."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)

    def pantalla(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_la_tabla_tiene_las_seis_columnas(self):
        respuesta = self.pantalla()
        for columna in ('Nombre', 'Cédula', 'correo', 'Carrera', 'Rol', 'Estado'):
            self.assertContains(respuesta, columna)

    def test_muestra_las_carreras_del_estudiante(self):
        estudiante = self.crear_usuario(
            'luis.mora@ejemplo.edu.co',
            nombre='Luis Mora',
            cedula='1033333333',
            rol=self.rol_estudiante,
        )
        inscripcion = self.inscribir_en_carrera(
            estudiante, 'Ingeniería de Sistemas', 'IS-01'
        )
        EstudianteCarrera.objects.create(
            estudiante=inscripcion.estudiante,
            carrera=self.crear_carrera('Ingeniería Civil', 'IC-01'),
            estado=EstadoInscripcion.ACTIVO,
        )
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'Ingeniería de Sistemas')
        self.assertContains(respuesta, 'Ingeniería Civil')

    def test_muestra_la_carrera_vigente_del_director(self):
        usuario = self.crear_usuario(
            'dora.prado@ejemplo.edu.co',
            nombre='Dora Prado',
            cedula='1044444444',
            rol=Rol.objects.get(nombre='Director'),
        )
        director = Director.objects.create(usuario=usuario)
        DirectorCarrera.objects.create(
            director=director,
            carrera=self.crear_carrera('Ingeniería de Sistemas', 'IS-01'),
            fecha_inicio=timezone.localdate(),
            activo=True,
        )
        DirectorCarrera.objects.create(
            director=director,
            carrera=self.crear_carrera('Ingeniería Civil', 'IC-01'),
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate(),
            activo=False,
        )
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'Ingeniería de Sistemas')
        self.assertNotContains(respuesta, 'Ingeniería Civil')

    def test_si_no_tiene_carrera_la_celda_queda_vacia(self):
        respuesta = self.pantalla()
        self.assertEqual(respuesta.context['usuarios'][0].carreras, [])


class ElRolAdministradorNoSeQuedaSinSalida(BaseRoles):
    """Lo encontró el revisor: vaciarle los permisos al rol base dejaba el
    sistema sin ninguna pantalla y sin forma de volver atrás."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.minimos = ['rol.ver', 'rol.editar', 'rol.asignar_permisos']

    def editar_administrador(self, permisos):
        return self.client.post(
            reverse('usuarios:rol_editar', args=[self.rol_administrador.pk]),
            {
                'nombre': self.rol_administrador.nombre,
                'descripcion': self.rol_administrador.descripcion,
                'permisos': list(
                    Permiso.objects.filter(nombre__in=permisos).values_list('pk', flat=True)
                ),
            },
        )

    def permisos_del_administrador(self):
        return set(
            Permiso.objects.filter(asignaciones__rol=self.rol_administrador).values_list(
                'nombre', flat=True
            )
        )

    def test_no_se_le_pueden_quitar_todos_los_permisos(self):
        antes = self.permisos_del_administrador()
        respuesta = self.editar_administrador([])
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.permisos_del_administrador(), antes)

    def test_el_mensaje_dice_cuales_no_se_pueden_quitar(self):
        respuesta = self.editar_administrador([])
        errores = respuesta.context['formulario'].errors['permisos']
        self.assertEqual(len(errores), 1)
        for permiso in self.minimos:
            self.assertIn(permiso, errores[0])

    def test_despues_del_intento_el_sistema_sigue_accesible(self):
        self.editar_administrador([])
        self.assertEqual(self.client.get(reverse('usuarios:roles')).status_code, 200)
        self.assertEqual(self.client.get(reverse('usuarios:usuarios')).status_code, 200)

    def test_no_se_le_puede_quitar_solo_uno_de_los_minimos(self):
        for quitado in self.minimos:
            quedan = [p for p in self.minimos if p != quitado]
            respuesta = self.editar_administrador(quedan)
            self.assertEqual(respuesta.status_code, 200, f'dejó quitar {quitado}')
            self.assertIn(quitado, self.permisos_del_administrador())

    def test_los_demas_permisos_si_se_le_pueden_quitar(self):
        respuesta = self.editar_administrador(self.minimos)
        self.assertRedirects(respuesta, reverse('usuarios:roles'))
        self.assertEqual(self.permisos_del_administrador(), set(self.minimos))

    def test_con_los_minimos_todavia_se_puede_deshacer_el_cambio(self):
        # Esto es lo que hace que el mínimo sea el correcto: con esos tres se
        # vuelve a la pantalla y se reponen los demás.
        self.editar_administrador(self.minimos)
        self.assertEqual(self.client.get(reverse('usuarios:roles')).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse('usuarios:rol_editar', args=[self.rol_administrador.pk])
            ).status_code,
            200,
        )
        self.editar_administrador(self.minimos + ['usuario.ver', 'usuario.crear'])
        self.assertIn('usuario.crear', self.permisos_del_administrador())

    def test_a_los_otros_roles_base_si_se_les_puede_dejar_sin_permisos(self):
        # La guarda es solo del Administrador: Estudiante y Director no son
        # puerta de recuperación de nada.
        respuesta = self.client.post(
            reverse('usuarios:rol_editar', args=[self.rol_estudiante.pk]),
            {'nombre': 'Estudiante', 'descripcion': '', 'permisos': []},
        )
        self.assertRedirects(respuesta, reverse('usuarios:roles'))


class ArreglosDeLaRevision(BaseRoles):
    """Los cuatro CORREGIR del revisor, cada uno con su prueba."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.administrador)
        self.rol_director = Rol.objects.get(nombre='Director')
        self.sistemas = self.crear_carrera('Ingeniería de Sistemas', 'IS-01')
        self.civil = self.crear_carrera('Ingeniería Civil', 'IC-01')
        self.usuario = self.crear_usuario(
            'pedro.diaz@ejemplo.edu.co',
            nombre='Pedro Díaz',
            cedula='1055555555',
            rol=self.rol_estudiante,
        )

    def editar(self, usuario, **cambios):
        datos = {
            'nombre': usuario.nombre,
            'cedula': usuario.cedula,
            'correo_institucional': usuario.correo_institucional,
            'rol': usuario.rol_id,
            'carrera': '',
        }
        datos.update(cambios)
        return self.client.post(
            reverse('usuarios:usuario_editar', args=[usuario.pk]), datos
        )

    def ultima(self):
        return Auditoria.objects.latest('id_auditoria')

    # --- C-1 · la auditoría guardaba "—" como carrera anterior ---

    def test_al_crear_un_director_la_auditoria_guarda_su_carrera(self):
        self.client.post(
            reverse('usuarios:usuario_nuevo'),
            {
                'nombre': 'Dora Prado',
                'cedula': '1044444444',
                'correo_institucional': 'dora.prado@ejemplo.edu.co',
                'rol': self.rol_director.pk,
                'carrera': self.sistemas.pk,
            },
        )
        self.assertIn('carrera: — → Ingeniería de Sistemas', self.ultima().detalle)

    def test_cambiarle_la_carrera_guarda_la_anterior_y_la_nueva(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.usuario.refresh_from_db()
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.civil.pk)
        self.assertIn(
            'carrera: Ingeniería de Sistemas → Ingeniería Civil', self.ultima().detalle
        )

    def test_quitarle_el_rol_de_director_deja_el_cierre_en_la_auditoria(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.usuario.refresh_from_db()
        self.editar(self.usuario, rol=self.rol_estudiante.pk, carrera='')
        detalle = self.ultima().detalle
        self.assertIn('rol: Director → Estudiante', detalle)
        self.assertIn('carrera: Ingeniería de Sistemas → — (asignación cerrada)', detalle)

    def test_si_la_carrera_no_cambia_no_se_inventa_una_linea(self):
        self.editar(self.usuario, nombre='Pedro Díaz Mora')
        self.assertNotIn('carrera', self.ultima().detalle)

    # --- C-2 · un Director con su carrera inactivada quedaba congelado ---

    def test_un_director_con_la_carrera_inactivada_se_puede_seguir_editando(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.usuario.refresh_from_db()
        # Lo hará SISTRA-11, que administra el catálogo de carreras.
        self.sistemas.estado = Estado.INACTIVO
        self.sistemas.save(update_fields=['estado'])

        respuesta = self.editar(
            self.usuario,
            nombre='Pedro Díaz Mora',
            rol=self.rol_director.pk,
            carrera=self.sistemas.pk,
        )
        self.assertRedirects(respuesta, reverse('usuarios:usuarios'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre, 'Pedro Díaz Mora')

    def test_la_pantalla_muestra_la_carrera_inactivada_del_director(self):
        self.editar(self.usuario, rol=self.rol_director.pk, carrera=self.sistemas.pk)
        self.sistemas.estado = Estado.INACTIVO
        self.sistemas.save(update_fields=['estado'])
        respuesta = self.client.get(
            reverse('usuarios:usuario_editar', args=[self.usuario.pk])
        )
        opciones = respuesta.context['formulario'].fields['carrera'].queryset
        self.assertIn(self.sistemas, opciones)

    # --- C-3 · el nombre de usuario quedaba contradiciendo al correo ---

    def test_al_cambiar_el_correo_se_vuelve_a_derivar_el_nombre_de_usuario(self):
        self.editar(self.usuario, correo_institucional='pedro.gomez@ejemplo.edu.co')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.correo_institucional, 'pedro.gomez@ejemplo.edu.co')
        self.assertEqual(self.usuario.nombre_usuario, 'pedro.gomez')

    def test_editar_sin_tocar_el_correo_no_le_pone_numero_al_nombre_de_usuario(self):
        self.editar(self.usuario, nombre='Pedro Díaz Mora')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre_usuario, 'pedro.diaz')

    def test_si_el_nombre_derivado_ya_esta_tomado_se_le_agrega_un_numero(self):
        self.crear_usuario(
            'pedro.gomez@otrodominio.edu.co', nombre='Pedro Homónimo', cedula='8888888888'
        )
        self.editar(self.usuario, correo_institucional='pedro.gomez@ejemplo.edu.co')
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.nombre_usuario, 'pedro.gomez-2')

    # --- O-6 · el botón de eliminar se ofrecía a quien nunca se puede borrar ---

    def test_no_se_ofrece_eliminar_a_un_estudiante_con_perfil(self):
        self.inscribir_en_carrera(self.usuario, 'Ingeniería Industrial', 'II-01')
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertNotContains(
            respuesta, reverse('usuarios:usuario_eliminar', args=[self.usuario.pk])
        )

    def test_si_se_ofrece_eliminar_a_una_cuenta_sin_perfil(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertContains(
            respuesta, reverse('usuarios:usuario_eliminar', args=[self.usuario.pk])
        )

    # --- O-5 · que nadie rompa el prefetch sin darse cuenta ---

    def test_la_lista_no_hace_consultas_por_fila(self):
        self.poblar(3, desde=20)
        with CaptureQueriesContext(connection) as con_pocos:
            self.client.get(reverse('usuarios:usuarios'))
        self.poblar(9, desde=40)
        with CaptureQueriesContext(connection) as con_muchos:
            self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(
            len(con_pocos.captured_queries),
            len(con_muchos.captured_queries),
            'la lista hace consultas por fila: se rompió el prefetch',
        )

    def poblar(self, cuantos, desde):
        for i in range(cuantos):
            usuario = self.crear_usuario(
                f'persona{desde + i}@ejemplo.edu.co',
                nombre=f'Persona {desde + i}',
                cedula=f'20{desde + i:08d}',
                rol=self.rol_estudiante,
            )
            self.inscribir_en_carrera(
                usuario, f'Carrera {desde + i}', f'C-{desde + i:03d}'
            )
