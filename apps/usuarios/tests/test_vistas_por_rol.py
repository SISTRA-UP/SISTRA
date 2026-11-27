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
from django.utils import timezone

from apps.parametrizacion.models import Carrera, Facultad
from apps.personas.models import Director, DirectorCarrera, Estudiante
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso
from apps.usuarios.permisos import (
    GRUPO_ADMINISTRACION,
    GRUPO_SIN_ROTULO,
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

    def test_cada_permiso_abre_exactamente_sus_opciones(self):
        """Un permiso ya no es una opción: `informe.aprobar` abre tres.

        Aprobación de informes (SISTRA-07), Verificar cargues de informes
        (SISTRA-09) y Documentos extra recibidos (PRO-16) son tres pantallas
        distintas que exigen el mismo permiso, así que la prueba compara
        contra todas las opciones de ese permiso, no contra una.
        """
        for permiso in dict.fromkeys(opcion.permiso for opcion in OPCIONES_DEL_MENU):
            with self.subTest(permiso=permiso):
                usuario = self.crear_usuario(
                    self.crear_rol_con(f'Solo {permiso}', permiso)
                )
                self.assertEqual(
                    self.etiquetas_de(usuario),
                    [
                        opcion.etiqueta
                        for opcion in OPCIONES_DEL_MENU
                        if opcion.permiso == permiso
                    ],
                )

    def test_un_rol_sin_permisos_no_ve_ninguna_opcion(self):
        usuario = self.crear_usuario(self.crear_rol_con('Sin permisos'))
        self.assertEqual(opciones_visibles(usuario), [])

    def test_un_rol_nuevo_ve_exactamente_sus_permisos(self):
        """C2: el ADMO crea un rol parcial y el menú lo refleja sin tocar código."""
        rol = self.crear_rol_con('Coordinador', 'rol.ver', 'informe.aprobar')
        usuario = self.crear_usuario(rol)

        self.assertEqual(
            self.etiquetas_de(usuario),
            [
                'Roles y permisos',
                'Aprobación de informes',
                'Verificar cargues de informes',
                'Documentos extra recibidos',
            ],
        )
        self.assertNotIn('Usuarios', self.etiquetas_de(usuario))

    def test_el_administrador_ve_lo_suyo(self):
        usuario = self.crear_usuario(self.rol_administrador)
        self.assertEqual(
            self.etiquetas_de(usuario),
            ['Inicio', 'Roles y permisos', 'Usuarios', 'Parametrización', 'Reportes'],
        )

    def test_el_director_ve_lo_suyo(self):
        usuario = self.crear_usuario(self.rol_director)
        self.assertEqual(
            self.etiquetas_de(usuario),
            [
                'Inicio',
                'Reportes',
                'Registrar estudiantes',
                'Aprobación de propuestas',
                'Verificar cargues de propuestas',
                'Aprobación de informes',
                'Verificar cargues de informes',
                'Documentos extra recibidos',
            ],
        )
        # Lo pide la tarjeta: el Director no administra el sistema.
        self.assertNotIn('Parametrización', self.etiquetas_de(usuario))

    def test_el_estudiante_ve_lo_suyo(self):
        usuario = self.crear_usuario(self.rol_estudiante)
        etiquetas = self.etiquetas_de(usuario)
        self.assertEqual(
            etiquetas,
            [
                'Inicio',
                'Mi propuesta',
                'Montar informe',
                'Cargue en la Plataforma UP',
            ],
        )
        self.assertNotIn('Roles y permisos', etiquetas)
        # Lo pide la tarjeta: ninguna aprobación, ni de propuestas ni de
        # informes, ni la verificación de cargues del Director.
        self.assertEqual(
            [etiqueta for etiqueta in etiquetas if 'probación' in etiqueta], []
        )
        self.assertEqual(
            [etiqueta for etiqueta in etiquetas if etiqueta.startswith('Verificar')], []
        )

    def test_inicio_apunta_al_dashboard_y_va_sin_rotulo(self):
        """«Inicio» no es administración ni un paso del trámite.

        En los mockups va suelto arriba, sin rótulo de grupo, así que su grupo
        no tiene título y el parcial no le pinta encabezado.
        """
        usuario = self.crear_usuario(self.crear_rol_con('Solo inicio', 'dashboard.ver'))
        grupos = opciones_visibles(usuario)

        self.assertEqual([grupo['titulo'] for grupo in grupos], [GRUPO_SIN_ROTULO])
        self.assertEqual(
            grupos[0]['opciones'],
            [{'etiqueta': 'Inicio', 'url': reverse('dashboard:inicio')}],
        )

    def test_cada_opcion_nueva_apunta_a_la_pantalla_que_le_toca(self):
        """Que la ruta resuelva no basta: tiene que ser la de su requisito.

        Con la ruta cambiada, el menú llevaría a otra pantalla y las pruebas de
        etiquetas pasarían igual, porque solo miran el texto.
        """
        esperado = {
            'Inicio': ('dashboard:inicio', GRUPO_SIN_ROTULO),
            'Reportes': ('reportes:reportes', GRUPO_ADMINISTRACION),
            'Verificar cargues de propuestas': (
                'cargue_up:verificacion_propuesta',
                GRUPO_TRAMITES,
            ),
            'Verificar cargues de informes': (
                'cargue_up:verificacion_informe_lista',
                GRUPO_TRAMITES,
            ),
            'Documentos extra recibidos': (
                'cargue_up:documentos_extra_recibidos',
                GRUPO_TRAMITES,
            ),
            'Mi propuesta': ('propuestas:montaje', GRUPO_TRAMITES),
        }
        catalogo = {opcion.etiqueta: opcion for opcion in OPCIONES_DEL_MENU}

        for etiqueta, (ruta, grupo) in esperado.items():
            with self.subTest(opcion=etiqueta):
                self.assertIn(etiqueta, catalogo)
                self.assertEqual(catalogo[etiqueta].ruta, ruta)
                self.assertEqual(catalogo[etiqueta].grupo, grupo)

    def test_el_permiso_de_cada_opcion_nueva_es_el_que_exige_su_pantalla(self):
        """El permiso no se elige: se copia del de la pantalla.

        Los dos de «Verificar cargues» no están en un decorador sino dentro de
        `director_y_carreras`, que lanza 403 si falta; se leen de la constante
        del propio módulo para que un cambio allá rompa aquí.

        «Mi propuesta» no tiene una constante equivalente: `propuestas:montaje`
        lleva el permiso literal en su decorador, así que aquí se afirma el
        literal, como con «Inicio» y «Reportes».
        """
        from apps.cargue_up.forms.verificacion_informe import (
            PERMISO_VERIFICAR as PERMISO_INFORME,
        )
        from apps.cargue_up.forms.verificacion_propuesta import (
            PERMISO_VERIFICAR as PERMISO_PROPUESTA,
        )

        catalogo = {opcion.etiqueta: opcion.permiso for opcion in OPCIONES_DEL_MENU}

        self.assertEqual(catalogo['Verificar cargues de propuestas'], PERMISO_PROPUESTA)
        self.assertEqual(catalogo['Verificar cargues de informes'], PERMISO_INFORME)
        self.assertEqual(catalogo['Inicio'], 'dashboard.ver')
        self.assertEqual(catalogo['Reportes'], 'reporte.descargar')
        self.assertEqual(catalogo['Documentos extra recibidos'], 'informe.aprobar')
        self.assertEqual(catalogo['Mi propuesta'], 'propuesta.montar')

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
        """Diagnóstico claro: ocho de los once permisos los siembran otros.

        Las 14 opciones usan 11 permisos distintos, y solo tres son de
        SISTRA-10. Vienen de migraciones de datos ajenas `sistema.parametrizar`
        (SISTRA-11), `propuesta.aprobar` (SISTRA-02), `propuesta.montar`
        (SISTRA-01), `informe.montar` (SISTRA-06), `informe.aprobar`
        (SISTRA-07), `cargue_up.avisar` (SISTRA-04), `dashboard.ver`
        (SISTRA-14) y `reporte.descargar` (SISTRA-12). Si una se cae, esta
        prueba dice cuál.
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

    def test_el_grupo_sin_titulo_no_deja_un_rotulo_vacio(self):
        """«Inicio» va suelto arriba: sin su `{% if %}`, el parcial pintaría
        un rótulo en blanco encima."""
        usuario = self.crear_usuario(self.crear_rol_con('Solo inicio', 'dashboard.ver'))
        peticion = self.peticion_de(usuario)

        dibujado = Template(PARCIAL).render(Context({'request': peticion}))

        self.assertIn('Inicio', dibujado)
        # No se mira la clase del rótulo sino el `<p>`: si R10 le cambia el
        # estilo, la prueba tiene que seguir cazando el rótulo en blanco.
        self.assertNotIn('<p', dibujado)

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

    def abrir_sin_tropiezos(self, destinos):
        """Cada destino abre: ni 403 ni rebote al login.

        Se sigue la redirección porque «Inicio» manda al panel del rol, que es
        otra URL; lo que no puede pasar es terminar en el login. Se compara con
        `startswith` y no por igualdad: `login_required` redirige a
        `/usuarios/login/?next=...`, que no es igual a la ruta del login, y el
        login responde 200, así que por igualdad el rebote pasaría inadvertido.
        """
        login = reverse('usuarios:login')
        self.assertTrue(destinos)
        for destino in destinos:
            with self.subTest(url=destino):
                respuesta = self.client.get(destino, follow=True)

                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(
                    [
                        paso for paso, _ in respuesta.redirect_chain
                        if paso.startswith(login)
                    ],
                    [],
                )

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

        Las tres son de requisitos ajenos y ninguna se contenta con el permiso:
        `propuestas:montaje` (SISTRA-01), `informes:montaje` (SISTRA-06) y
        `cargue_up:cargue_propuesta` (SISTRA-03) exigen además perfil de
        estudiante. Un Estudiante de verdad lo tiene, y esta prueba lo fija
        para que un cambio allá se note aquí. Los dos montajes responden 200
        con su propio mensaje cuando el estudiante todavía no tiene proceso
        activo ni propuesta aprobada en UP, que es el caso de esta prueba:
        siguen siendo pantallas que abren, no un 403.
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
            [
                reverse('dashboard:inicio'),
                reverse('propuestas:montaje'),
                reverse('informes:montaje'),
                reverse('cargue_up:cargue_propuesta'),
            ],
        )
        self.abrir_sin_tropiezos(destinos)

    def test_el_director_puede_abrir_las_opciones_que_ve(self):
        """Lo mismo para el Director, que es quien más opciones ve.

        Sus pantallas de «Verificar cargues» no se contentan con el permiso:
        `director_y_carreras` exige además un perfil de Director con una
        carrera asignada y activa. Un Director de verdad lo tiene.
        """
        usuario = self.crear_usuario(self.rol_director)
        facultad = Facultad.objects.create(nombre='Facultad de prueba SIS-74')
        carrera = Carrera.objects.create(
            facultad=facultad, nombre='Carrera de prueba SIS-74', codigo='S74-A'
        )
        DirectorCarrera.objects.create(
            director=Director.objects.create(usuario=usuario),
            carrera=carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )
        self.client.force_login(usuario)

        self.abrir_sin_tropiezos([
            opcion['url'] for grupo in opciones_visibles(usuario)
            for opcion in grupo['opciones']
        ])

    def test_el_cargue_csv_exige_los_dos_permisos(self):
        solo_uno = self.crear_rol_con('Registrador', 'estudiante.registrar')
        self.client.force_login(self.crear_usuario(solo_uno))

        respuesta = self.client.post(reverse('personas:estudiantes_csv'))

        self.assertEqual(respuesta.status_code, 403)
