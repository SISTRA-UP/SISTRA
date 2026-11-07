"""SISTRA-10 · Roles (roles, permisos y usuarios): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import EstadoInscripcion, Estudiante, EstudianteCarrera
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
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
        )

    def crear_rol_con(self, nombre, *permisos):
        """Un rol con solo esos permisos, para probar cada guarda por separado."""
        rol = Rol.objects.create(nombre=nombre)
        for permiso in Permiso.objects.filter(nombre__in=permisos):
            RolPermiso.objects.create(rol=rol, permiso=permiso)
        return rol

    def inscribir_en_carrera(self, usuario, nombre_carrera, codigo_carrera):
        """Deja al usuario como estudiante inscrito en una carrera."""
        facultad, _ = Facultad.objects.get_or_create(nombre='Facultad de Prueba')
        carrera = Carrera.objects.create(
            facultad=facultad, nombre=nombre_carrera, codigo=codigo_carrera
        )
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
        self.assertEqual(administrador.total_permisos, len(PERMISOS_DE_SISTRA_10))

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

    def test_no_existe_ninguna_ruta_para_eliminar_usuarios(self):
        # La regla §17 manda desactivar, no eliminar.
        with self.assertRaises(NoReverseMatch):
            reverse('usuarios:usuario_eliminar', args=[self.estudiante.pk])

    def test_la_pantalla_no_ofrece_eliminar(self):
        respuesta = self.client.get(reverse('usuarios:usuarios'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Inactivar')
        self.assertNotContains(respuesta, 'Eliminar')
        self.assertNotContains(respuesta, 'Borrar')

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
