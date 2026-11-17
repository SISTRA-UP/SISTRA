"""SISTRA-10 · Vistas por rol: menú por permisos y acceso a las URL protegidas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from apps.personas.models import Estudiante
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso
from apps.usuarios.permisos import (
    GRUPO_ADMINISTRACION,
    GRUPO_TRAMITES,
    OPCIONES_DEL_MENU,
    Opcion,
    opciones_visibles,
)

Usuario = get_user_model()

PARCIAL = "{% include 'usuarios/roles/_menu.html' %}"

# Cada URL protegida de SISTRA-10 con los permisos que la habilitan. Las de
# `rol_estado`, `usuario_estado`, `usuario_eliminar` y `estudiantes_csv` solo
# aceptan POST, pero la guarda se evalúa antes que el método, así que la
# redirección al login y el 403 se comprueban igual.
RUTAS_PROTEGIDAS = [
    ('usuarios:roles', (), ('rol.ver',)),
    ('usuarios:rol_nuevo', (), ('rol.crear',)),
    ('usuarios:rol_editar', (999,), ('rol.editar',)),
    ('usuarios:rol_estado', (999,), ('rol.inactivar',)),
    ('usuarios:usuarios', (), ('usuario.ver',)),
    ('usuarios:usuario_nuevo', (), ('usuario.crear',)),
    ('usuarios:usuario_editar', (999,), ('usuario.editar',)),
    ('usuarios:usuario_estado', (999,), ('usuario.inactivar',)),
    ('usuarios:usuario_eliminar', (999,), ('usuario.eliminar',)),
    ('personas:estudiantes', (), ('estudiante.registrar',)),
    # El cargue masivo exige los dos permisos.
    ('personas:estudiantes_csv', (), ('estudiante.registrar', 'estudiante.cargar_csv')),
]


class BaseVistasPorRol(TestCase):
    """Los roles base y los permisos los siembran las migraciones de datos."""

    def setUp(self):
        self.rol_administrador = Rol.objects.get(nombre='Administrador')
        self.rol_director = Rol.objects.get(nombre='Director')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.contador = 0

    def crear_usuario(self, rol, nombre='Persona de prueba'):
        self.contador += 1
        correo = f'persona{self.contador}@unipamplona.edu.co'
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password='ClaveDePrueba123',
            nombre=nombre,
            cedula=f'20000000{self.contador:02d}',
            nombre_usuario=correo.split('@')[0],
            rol=rol,
            requiere_cambio_contrasena=False,
        )

    def crear_rol_con(self, nombre, *permisos):
        """Un rol con solo esos permisos, como el que crearía el ADMO."""
        rol = Rol.objects.create(nombre=nombre)
        encontrados = Permiso.objects.filter(nombre__in=permisos)
        # Si un requisito ajeno retira la migración que siembra su permiso, el
        # filtro lo descartaría en silencio y la prueba fallaría más adelante
        # como si el menú estuviera mal. Mejor fallar aquí y con el nombre.
        faltantes = set(permisos) - {permiso.nombre for permiso in encontrados}
        self.assertFalse(
            faltantes,
            f'No están sembrados en la tabla `permiso`: {sorted(faltantes)}. '
            'Lo siembra una migración de datos; revisa si su requisito la retiró.',
        )
        for permiso in encontrados:
            RolPermiso.objects.create(rol=rol, permiso=permiso)
        return rol

    def etiquetas_de(self, usuario):
        """Las etiquetas que ese usuario ve en el menú, sin los grupos."""
        return [
            opcion['etiqueta']
            for grupo in opciones_visibles(usuario)
            for opcion in grupo['opciones']
        ]


class MenuPorPermisos(BaseVistasPorRol):
    """C1 y C2: el menú se arma por permiso, no por el nombre del rol."""

    def test_cada_opcion_aparece_solo_con_su_permiso(self):
        for opcion in OPCIONES_DEL_MENU:
            with self.subTest(permiso=opcion.permiso):
                rol = self.crear_rol_con(f'Solo {opcion.permiso}', opcion.permiso)
                usuario = self.crear_usuario(rol)
                self.assertEqual(self.etiquetas_de(usuario), [opcion.etiqueta])

    def test_un_rol_sin_permisos_no_ve_ninguna_opcion(self):
        usuario = self.crear_usuario(self.crear_rol_con('Sin permisos'))
        self.assertEqual(opciones_visibles(usuario), [])

    def test_un_rol_nuevo_ve_exactamente_sus_permisos(self):
        """C2: el ADMO crea un rol parcial y el menú lo refleja sin tocar código."""
        rol = self.crear_rol_con('Coordinador', 'rol.ver', 'informe.aprobar')
        usuario = self.crear_usuario(rol)

        self.assertEqual(
            self.etiquetas_de(usuario),
            ['Roles y permisos', 'Aprobación de informes'],
        )
        self.assertNotIn('Usuarios', self.etiquetas_de(usuario))

    def test_el_administrador_ve_lo_suyo(self):
        usuario = self.crear_usuario(self.rol_administrador)
        self.assertEqual(
            self.etiquetas_de(usuario),
            ['Roles y permisos', 'Usuarios', 'Parametrización'],
        )

    def test_el_director_ve_lo_suyo(self):
        usuario = self.crear_usuario(self.rol_director)
        self.assertEqual(
            self.etiquetas_de(usuario),
            [
                'Registrar estudiantes',
                'Aprobación de propuestas',
                'Aprobación de informes',
            ],
        )

    def test_el_estudiante_ve_lo_suyo(self):
        usuario = self.crear_usuario(self.rol_estudiante)
        self.assertEqual(
            self.etiquetas_de(usuario),
            ['Montar informe', 'Cargue en la Plataforma UP'],
        )
        self.assertNotIn('Roles y permisos', self.etiquetas_de(usuario))

    def test_montar_informe_sale_solo_con_su_permiso(self):
        """Los dos casos del criterio, en una sola prueba."""
        con_permiso = self.crear_usuario(
            self.crear_rol_con('Monta informes', 'informe.montar')
        )
        sin_permiso = self.crear_usuario(self.crear_rol_con('Sin informes', 'rol.ver'))

        self.assertIn('Montar informe', self.etiquetas_de(con_permiso))
        self.assertNotIn('Montar informe', self.etiquetas_de(sin_permiso))

    def test_montar_informe_apunta_al_montaje_de_informes(self):
        """Que la ruta resuelva no basta: tiene que ser la de SISTRA-06.

        Y tiene que salir bajo «Trámites»: el grupo no lo comprobaba ninguna
        otra prueba, porque `etiquetas_de` aplana los grupos y pierde el
        título. Con el grupo equivocado, la opción aparecería bajo
        «Administración» en el menú del estudiante y la suite pasaría igual.
        """
        usuario = self.crear_usuario(
            self.crear_rol_con('Monta informes', 'informe.montar')
        )
        grupos = opciones_visibles(usuario)
        opciones = [opcion for grupo in grupos for opcion in grupo['opciones']]

        self.assertEqual([grupo['titulo'] for grupo in grupos], [GRUPO_TRAMITES])
        self.assertEqual(len(opciones), 1)
        self.assertEqual(opciones[0]['url'], reverse('informes:montaje'))

    def test_el_anonimo_no_ve_opciones(self):
        self.assertEqual(opciones_visibles(AnonymousUser()), [])
        self.assertEqual(opciones_visibles(None), [])

    def test_un_rol_inactivo_se_queda_sin_opciones(self):
        rol = self.crear_rol_con('Temporal', 'rol.ver')
        usuario = self.crear_usuario(rol)
        rol.estado = Estado.INACTIVO
        rol.save()

        self.assertEqual(opciones_visibles(Usuario.objects.get(pk=usuario.pk)), [])

    def test_un_usuario_inactivo_se_queda_sin_opciones(self):
        usuario = self.crear_usuario(self.rol_administrador)
        usuario.estado = Estado.INACTIVO
        usuario.save()

        self.assertEqual(opciones_visibles(usuario), [])

    def test_una_ruta_que_no_resuelve_se_omite_sin_romper_el_menu(self):
        """Si otro requisito renombra su ruta, desaparece la opción, no la página."""
        fantasma = Opcion(
            'rol.ver', 'usuarios:ruta_inexistente', 'Fantasma', GRUPO_ADMINISTRACION
        )
        usuario = self.crear_usuario(self.rol_administrador)

        with patch('apps.usuarios.permisos.OPCIONES_DEL_MENU', (fantasma,)):
            self.assertEqual(opciones_visibles(usuario), [])

    def test_cada_permiso_del_catalogo_esta_sembrado(self):
        """Diagnóstico claro: cinco de los ocho permisos los siembran otros.

        `sistema.parametrizar` (SISTRA-11), `propuesta.aprobar` (SISTRA-02),
        `informe.montar` (SISTRA-06), `informe.aprobar` (SISTRA-07) y
        `cargue_up.avisar` (SISTRA-04) vienen de migraciones de datos ajenas.
        Si una se cae, esta prueba dice cuál.
        """
        sembrados = set(Permiso.objects.values_list('nombre', flat=True))
        for opcion in OPCIONES_DEL_MENU:
            with self.subTest(permiso=opcion.permiso):
                self.assertIn(opcion.permiso, sembrados)

    def test_cada_opcion_del_catalogo_apunta_a_una_ruta_que_existe(self):
        usuario = self.crear_usuario(self.crear_rol_con('Todo', *[
            opcion.permiso for opcion in OPCIONES_DEL_MENU
        ]))
        self.assertEqual(len(self.etiquetas_de(usuario)), len(OPCIONES_DEL_MENU))


class ParcialDelMenu(BaseVistasPorRol):
    """C4: `{% include %}` basta, sin contexto de la vista y sin `{% load %}`."""

    def peticion_de(self, usuario, ruta='/'):
        peticion = RequestFactory().get(ruta)
        peticion.user = usuario
        return peticion

    def test_se_incluye_desde_una_plantilla_cualquiera(self):
        usuario = self.crear_usuario(self.rol_administrador)
        peticion = self.peticion_de(usuario)

        dibujado = Template(PARCIAL).render(Context({'request': peticion}))

        self.assertIn('Roles y permisos', dibujado)
        self.assertIn(reverse('usuarios:roles'), dibujado)
        self.assertNotIn('Registrar estudiantes', dibujado)

    def test_el_parcial_no_pinta_nada_para_el_anonimo(self):
        peticion = self.peticion_de(AnonymousUser())

        dibujado = Template(PARCIAL).render(Context({'request': peticion}))

        self.assertNotIn('<nav', dibujado)
        self.assertEqual(dibujado.strip(), '')

    def test_marca_la_opcion_de_la_pagina_actual(self):
        usuario = self.crear_usuario(self.rol_administrador)
        peticion = self.peticion_de(usuario, reverse('usuarios:roles'))

        dibujado = Template(PARCIAL).render(Context({'request': peticion}))

        self.assertIn('aria-current="page"', dibujado)

    def test_la_pantalla_de_roles_trae_el_menu(self):
        self.client.force_login(self.crear_usuario(self.rol_administrador))

        respuesta = self.client.get(reverse('usuarios:roles'))

        self.assertContains(respuesta, 'Opciones disponibles para tu rol')
        self.assertContains(respuesta, 'Parametrización')

    def test_la_pantalla_del_director_trae_su_propio_menu(self):
        self.client.force_login(self.crear_usuario(self.rol_director))

        respuesta = self.client.get(reverse('personas:estudiantes'))

        self.assertContains(respuesta, 'Aprobación de propuestas')
        self.assertNotContains(respuesta, 'Roles y permisos')


class AccesoALasUrlProtegidas(BaseVistasPorRol):
    """C3: sin sesión va al login; con sesión y sin el permiso, 403."""

    def test_sin_sesion_va_al_login(self):
        for nombre, argumentos, _ in RUTAS_PROTEGIDAS:
            with self.subTest(ruta=nombre):
                destino = reverse(nombre, args=argumentos)

                respuesta = self.client.get(destino)

                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(
                    respuesta.url.startswith(reverse('usuarios:login')),
                    f'{nombre} redirige a {respuesta.url}',
                )
                self.assertIn(destino, respuesta.url)

    def test_con_sesion_pero_sin_el_permiso_responde_403(self):
        self.client.force_login(self.crear_usuario(self.crear_rol_con('Mirón')))

        for nombre, argumentos, _ in RUTAS_PROTEGIDAS:
            with self.subTest(ruta=nombre):
                respuesta = self.client.get(reverse(nombre, args=argumentos))
                self.assertEqual(respuesta.status_code, 403)

    def test_con_el_permiso_justo_entra(self):
        rol = self.crear_rol_con('Auditor', 'rol.ver')
        self.client.force_login(self.crear_usuario(rol))

        self.assertEqual(self.client.get(reverse('usuarios:roles')).status_code, 200)
        self.assertEqual(self.client.get(reverse('usuarios:usuarios')).status_code, 403)

    def test_cada_ruta_deja_pasar_a_quien_tiene_su_permiso(self):
        """La guarda no se pasa de celosa: con su permiso, la ruta no bloquea.

        No se afirma 200 porque varias solo aceptan POST (405) y otras buscan un
        registro que no existe (404): lo que importa es que ni redirige al login
        ni responde 403, o sea que la guarda dejó pasar.
        """
        for indice, (nombre, argumentos, permisos) in enumerate(RUTAS_PROTEGIDAS):
            with self.subTest(ruta=nombre):
                rol = self.crear_rol_con(f'Permitido {indice}', *permisos)
                self.client.force_login(self.crear_usuario(rol))

                respuesta = self.client.get(reverse(nombre, args=argumentos))

                self.assertNotIn(respuesta.status_code, (302, 403))

    def test_el_estudiante_puede_abrir_las_opciones_que_ve(self):
        """Ninguna opción del Estudiante puede darle 403 al abrirla.

        Las dos son de requisitos ajenos y ninguna se contenta con el permiso:
        `cargue_up:cargue_propuesta` (SISTRA-03) e `informes:montaje`
        (SISTRA-06) exigen además perfil de estudiante. Un Estudiante de verdad
        lo tiene, y esta prueba lo fija para que un cambio allá se note aquí.
        El montaje responde 200 con su propio mensaje cuando el estudiante
        todavía no tiene propuesta aprobada en UP, que es el caso de esta
        prueba: sigue siendo una pantalla que abre, no un 403.
        """
        usuario = self.crear_usuario(self.rol_estudiante)
        Estudiante.objects.create(usuario=usuario)
        self.client.force_login(usuario)

        destinos = [
            opcion['url'] for grupo in opciones_visibles(usuario)
            for opcion in grupo['opciones']
        ]
        self.assertEqual(
            destinos,
            [reverse('informes:montaje'), reverse('cargue_up:cargue_propuesta')],
        )
        for destino in destinos:
            with self.subTest(url=destino):
                self.assertEqual(self.client.get(destino).status_code, 200)

    def test_el_cargue_csv_exige_los_dos_permisos(self):
        solo_uno = self.crear_rol_con('Registrador', 'estudiante.registrar')
        self.client.force_login(self.crear_usuario(solo_uno))

        respuesta = self.client.post(reverse('personas:estudiantes_csv'))

        self.assertEqual(respuesta.status_code, 403)
