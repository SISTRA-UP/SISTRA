
"""Pruebas de integración para el módulo de reportes."""

from unittest.mock import patch
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.usuarios.models import Rol, Permiso, RolPermiso
from apps.personas.models import (
    Director,
    DirectorCarrera,
    Estudiante,
    EstudianteCarrera,
    EstadoInscripcion,
)
from apps.parametrizacion.models import (
    Facultad,
    Carrera,
    PeriodoAcademico,
    EstadoPeriodo,
    TipoRechazo,
)
from apps.procesos.models import ProcesoTrabajoSocial, EstadoAvance
from apps.propuestas.models import (
    Propuesta,
    EstadoTramite,
    SectorEntidad,
)
from apps.informes.models import Informe
from apps.seguimiento.models import Auditoria, HistorialEstado
from apps.reportes.services.report_service import (
    obtener_datos_reporte_trabajo_social,
)


Usuario = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class TestAccesoReportes(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.rol_director, _ = Rol.objects.get_or_create(nombre='Director')
        cls.rol_admin, _ = Rol.objects.get_or_create(nombre='Administrador')
        cls.rol_estudiante, _ = Rol.objects.get_or_create(nombre='Estudiante')

        # Permiso de acceso a reportes
        cls.permiso_reportes, _ = Permiso.objects.get_or_create(
            nombre='reporte.descargar'
        )

        # Asignar permiso a Director y Administrador
        RolPermiso.objects.get_or_create(
            rol=cls.rol_director,
            permiso=cls.permiso_reportes,
        )
        RolPermiso.objects.get_or_create(
            rol=cls.rol_admin,
            permiso=cls.permiso_reportes,
        )

        # Facultad y carrera
        cls.facultad = Facultad.objects.create(
            nombre='Facultad de Ingeniería'
        )
        cls.carrera = Carrera.objects.create(
            facultad=cls.facultad,
            nombre='Ingeniería de Sistemas',
            codigo='TEST-IS',
        )

        # Usuario Director
        cls.usuario_director = Usuario.objects.create_user(
            correo_institucional='director@test.com',
            password='Prueba123*',
            rol=cls.rol_director,
            nombre='Director de Prueba',
            cedula='100000001',
            nombre_usuario='director_test',
            requiere_cambio_contrasena=False,
        )

        cls.director = Director.objects.create(
            usuario=cls.usuario_director
        )

        # Usuario Administrador
        cls.usuario_admin = Usuario.objects.create_user(
            correo_institucional='admin@test.com',
            password='Prueba123*',
            rol=cls.rol_admin,
            nombre='Administrador de Prueba',
            cedula='100000002',
            nombre_usuario='admin_test',
            requiere_cambio_contrasena=False,
        )

        # Usuario Estudiante
        cls.usuario_estudiante = Usuario.objects.create_user(
            correo_institucional='estudiante@test.com',
            password='Prueba123*',
            rol=cls.rol_estudiante,
            nombre='Estudiante de Prueba',
            cedula='100000003',
            nombre_usuario='estudiante_test',
            requiere_cambio_contrasena=False,
        )

    def setUp(self):
        self.url = reverse('reportes:reportes')

    def test_usuario_sin_sesion_es_redirigido_al_login(self):
        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 302)

    def test_estudiante_no_puede_acceder_a_reportes(self):
        self.client.force_login(self.usuario_estudiante)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 403)

    def test_director_sin_carrera_activa_recibe_403(self):
        self.client.force_login(self.usuario_director)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 403)

    def test_director_con_carrera_activa_puede_acceder(self):
        DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=date(2026, 1, 1),
            activo=True,
        )

        self.client.force_login(self.usuario_director)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 200)

        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.usuario_director,
                accion='reporte_acceso',
                tabla_afectada='reporte',
                resultado='Éxito',
            ).exists()
        )

    def test_administrador_puede_acceder_a_reportes(self):
        self.client.force_login(self.usuario_admin)

        respuesta = self.client.get(self.url)

        self.assertEqual(respuesta.status_code, 200)

        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.usuario_admin,
                accion='reporte_acceso',
                tabla_afectada='reporte',
                resultado='Éxito',
            ).exists()
        )


@override_settings(SECURE_SSL_REDIRECT=False)
class TestAislamientoReportes(TestCase):

    @classmethod
    def setUpTestData(cls):
        # -------------------------------------------------
        # 1. ROLES Y PERMISOS
        # -------------------------------------------------

        cls.rol_director, _ = Rol.objects.get_or_create(
            nombre='Director'
        )
        cls.rol_admin, _ = Rol.objects.get_or_create(
            nombre='Administrador'
        )
        cls.rol_estudiante, _ = Rol.objects.get_or_create(
            nombre='Estudiante'
        )
        cls.tipo_rechazo, _ = TipoRechazo.objects.get_or_create(
            nombre='Documentación incompleta',defaults={'estado': 'Activo'},
            )

        cls.permiso_reportes, _ = Permiso.objects.get_or_create(
            nombre='reporte.descargar'
        )
        cls.permiso_todas, _ = Permiso.objects.get_or_create(
            nombre='reporte.descargar_todas'
        )

        RolPermiso.objects.get_or_create(
            rol=cls.rol_director,
            permiso=cls.permiso_reportes,
        )
        RolPermiso.objects.get_or_create(
            rol=cls.rol_admin,
            permiso=cls.permiso_reportes,
        )
        RolPermiso.objects.get_or_create(
            rol=cls.rol_admin,
            permiso=cls.permiso_todas,
        )

        # -------------------------------------------------
        # 2. FACULTAD Y CARRERAS
        # -------------------------------------------------

        cls.facultad = Facultad.objects.create(
            nombre='Facultad de Pruebas de Reportes'
        )

        cls.carrera_a = Carrera.objects.create(
            facultad=cls.facultad,
            nombre='Ingeniería de Sistemas A',
            codigo='TEST-REP-A',
        )

        cls.carrera_b = Carrera.objects.create(
            facultad=cls.facultad,
            nombre='Ingeniería de Sistemas B',
            codigo='TEST-REP-B',
        )

        # -------------------------------------------------
        # 3. DIRECTORES
        # -------------------------------------------------

        cls.usuario_director_a = Usuario.objects.create_user(
            correo_institucional='director_a@test.com',
            password='Prueba123*',
            rol=cls.rol_director,
            nombre='Director Carrera A',
            cedula='200000001',
            nombre_usuario='director_a',
            requiere_cambio_contrasena=False,
        )

        cls.usuario_director_b = Usuario.objects.create_user(
            correo_institucional='director_b@test.com',
            password='Prueba123*',
            rol=cls.rol_director,
            nombre='Director Carrera B',
            cedula='200000002',
            nombre_usuario='director_b',
            requiere_cambio_contrasena=False,
        )

        cls.director_a = Director.objects.create(
            usuario=cls.usuario_director_a
        )
        cls.director_b = Director.objects.create(
            usuario=cls.usuario_director_b
        )

        DirectorCarrera.objects.create(
            director=cls.director_a,
            carrera=cls.carrera_a,
            fecha_inicio=date(2026, 1, 1),
            activo=True,
        )

        DirectorCarrera.objects.create(
            director=cls.director_b,
            carrera=cls.carrera_b,
            fecha_inicio=date(2026, 1, 1),
            activo=True,
        )

        # -------------------------------------------------
        # 4. ADMINISTRADOR
        # -------------------------------------------------

        cls.usuario_admin = Usuario.objects.create_user(
            correo_institucional='admin_aislamiento@test.com',
            password='Prueba123*',
            rol=cls.rol_admin,
            nombre='Administrador Reportes',
            cedula='200000003',
            nombre_usuario='admin_reportes',
            requiere_cambio_contrasena=False,
        )

        # -------------------------------------------------
        # 5. PERIODO ACADÉMICO
        # -------------------------------------------------

        cls.periodo = PeriodoAcademico.objects.create(
            nombre='TEST-2026',
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
            fecha_cierre_propuesta=date(2026, 6, 30),
            fecha_cierre_informe=date(2026, 7, 30),
            estado=EstadoPeriodo.CERRADO,
        )

        # -------------------------------------------------
        # 6. INFORMES DE LAS DOS CARRERAS
        # -------------------------------------------------

        cls._crear_informe_aprobado(
            carrera=cls.carrera_a,
            codigo='TEST-PROP-A',
            codigo_informe='TEST-INF-A',
            nombre_estudiante='Estudiante Carrera A',
            cedula='300000001',
            correo='estudiante_a@test.com',
            nombre_usuario='estudiante_a',
            entidad='Alcaldía A',
            sector=SectorEntidad.PUBLICO,
        )

        cls._crear_informe_aprobado(
            carrera=cls.carrera_b,
            codigo='TEST-PROP-B',
            codigo_informe='TEST-INF-B',
            nombre_estudiante='Estudiante Carrera B',
            cedula='300000002',
            correo='estudiante_b@test.com',
            nombre_usuario='estudiante_b',
            entidad='Empresa B',
            sector=SectorEntidad.PRIVADO,
        )

    @classmethod
    def _crear_informe_aprobado(
        cls,
        carrera,
        codigo,
        codigo_informe,
        nombre_estudiante,
        cedula,
        correo,
        nombre_usuario,
        entidad,
        sector,
    ):
        # Usuario y estudiante
        usuario = Usuario.objects.create_user(
            correo_institucional=correo,
            password='Prueba123*',
            rol=cls.rol_estudiante,
            nombre=nombre_estudiante,
            cedula=cedula,
            nombre_usuario=nombre_usuario,
            requiere_cambio_contrasena=False,
        )

        estudiante = Estudiante.objects.create(
            usuario=usuario
        )

        # Inscripción en carrera
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=carrera,
            estado=EstadoInscripcion.ACTIVO,
        )

        # Proceso de Trabajo Social
        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.EN_CURSO,
        )

        # Propuesta
        propuesta = Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=cls.periodo,
            codigo=codigo,
            titulo=f'Propuesta de prueba {codigo}',
            entidad=entidad,
            sector_entidad=sector,
            poblacion_beneficiada='Comunidad de prueba',
            zona='Urbana',
            area='Social',
            sector='Comunitario',
            unidad='Unidad de prueba',
            estado=EstadoTramite.APROBADO_EN_UP,
            fecha_envio=timezone.now(),
        )

        # Informe aprobado
        informe = Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=cls.periodo,
            codigo=codigo_informe,
            estado=EstadoTramite.APROBADO_EN_UP,
            fecha_envio=timezone.now(),
        )

        # Historial necesario para obtener la fecha de decisión
        HistorialEstado.objects.create(
            informe=informe,
            usuario=cls.usuario_admin,
            estado_nuevo=EstadoTramite.APROBADO_EN_UP,
            estado_anterior=EstadoTramite.SUBIDO_EN_UP,
            tipo_accion='Aprobación',
            observacion='Aprobado para prueba de integración',
            fecha_hora=timezone.now(),
        )

    @classmethod
    def _crear_propuesta_rechazada(cls):
        usuario = Usuario.objects.create_user(
            correo_institucional='rechazado@test.com',
            password='Prueba123*',
            rol=cls.rol_estudiante,
            nombre='Estudiante Propuesta Rechazada',
            cedula='100000010',
            nombre_usuario='estudiante_rechazado',
            requiere_cambio_contrasena=False,
        )

        estudiante = Estudiante.objects.create(
            usuario=usuario
        )

        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=cls.carrera_a,
            estado=EstadoInscripcion.ACTIVO,
        )

        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.EN_CURSO,
        )

        propuesta = Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=cls.periodo,
            codigo='PROP-RECH-001',
            titulo='Propuesta rechazada de prueba',
            entidad='Entidad de prueba',
            sector_entidad=SectorEntidad.PUBLICO,
            poblacion_beneficiada='Comunidad de prueba',
            zona='Urbana',
            area='Social',
            sector='Comunitario',
            unidad='Unidad de prueba',
            estado=EstadoTramite.RECHAZADO,
            fecha_envio=timezone.now(),
        )

        HistorialEstado.objects.create(
            propuesta=propuesta,
            usuario=cls.usuario_admin,
            tipo_rechazo=cls.tipo_rechazo,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.RECHAZADO,
            tipo_accion='Rechazo',
            observacion='Falta documentación de soporte',
            fecha_hora=timezone.now(),
        )

        return propuesta

    @classmethod
    def _crear_informe_rechazado(cls):
        usuario = Usuario.objects.create_user(
            correo_institucional='informe.rechazado@test.com',
            password='Prueba123*',
            rol=cls.rol_estudiante,
            nombre='Estudiante Informe Rechazado',
            cedula='100000011',
            nombre_usuario='informe_rechazado',
            requiere_cambio_contrasena=False,
        )

        estudiante = Estudiante.objects.create(
            usuario=usuario
        )

        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=cls.carrera_a,
            estado=EstadoInscripcion.ACTIVO,
        )

        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.EN_CURSO,
        )

        propuesta = Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=cls.periodo,
            codigo='PROP-INF-RECH-001',
            titulo='Propuesta para informe rechazado',
            entidad='Entidad de prueba',
            sector_entidad=SectorEntidad.PUBLICO,
            poblacion_beneficiada='Comunidad de prueba',
            zona='Urbana',
            area='Social',
            sector='Comunitario',
            unidad='Unidad de prueba',
            estado=EstadoTramite.APROBADO_EN_UP,
            fecha_envio=timezone.now(),
        )

        informe = Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=cls.periodo,
            codigo='INF-RECH-001',
            estado=EstadoTramite.RECHAZADO,
            fecha_envio=timezone.now(),
        )

        HistorialEstado.objects.create(
            informe=informe,
            usuario=cls.usuario_admin,
            tipo_rechazo=cls.tipo_rechazo,
            estado_anterior=EstadoTramite.SUBIDO_EN_UP,
            estado_nuevo=EstadoTramite.RECHAZADO,
            tipo_accion='Rechazo',
            observacion='El informe no contiene las evidencias requeridas',
            fecha_hora=timezone.now(),
        )

        return informe

    # -------------------------------------------------
    # 7. PRUEBAS DE AISLAMIENTO
    # -------------------------------------------------

    def test_director_a_solo_recibe_datos_de_su_carrera(self):
        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_director_a
        )

        self.assertEqual(len(datos['aprobados']), 1)

        self.assertEqual(
            datos['aprobados'][0]['carrera'],
            'Ingeniería de Sistemas A',
        )

        self.assertEqual(
            datos['aprobados'][0]['nombre'],
            'Estudiante Carrera A',
        )

        self.assertFalse(datos['incluir_carrera'])

    def test_director_b_solo_recibe_datos_de_su_carrera(self):
        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_director_b
        )

        self.assertEqual(len(datos['aprobados']), 1)

        self.assertEqual(
            datos['aprobados'][0]['carrera'],
            'Ingeniería de Sistemas B',
        )

        self.assertEqual(
            datos['aprobados'][0]['nombre'],
            'Estudiante Carrera B',
        )

        self.assertFalse(datos['incluir_carrera'])

    def test_administrador_recibe_datos_de_todas_las_carreras(self):
        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin
        )

        self.assertEqual(len(datos['aprobados']), 2)

        carreras = {
            registro['carrera']
            for registro in datos['aprobados']
        }

        self.assertEqual(
            carreras,
            {
                'Ingeniería de Sistemas A',
                'Ingeniería de Sistemas B',
            },
        )

        self.assertTrue(datos['incluir_carrera'])

    def test_resumen_del_administrador_cuenta_entidades_por_sector(self):
        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin
        )

        self.assertEqual(
            datos['resumen']['total_estudiantes'],
            2,
        )

        self.assertEqual(
            datos['resumen']['entidades_publicas'],
            1,
        )

        self.assertEqual(
            datos['resumen']['entidades_privadas'],
            1,
        )

    def test_propuesta_rechazada_aparece_con_motivo_y_observacion(self):
        self._crear_propuesta_rechazada()

        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin
        )

        self.assertEqual(len(datos['rechazados']), 1)

        rechazado = datos['rechazados'][0]

        self.assertEqual(
            rechazado['tipo_rechazo'],
            'Documentación incompleta',
        )

        self.assertEqual(
            rechazado['observacion'],
            'Falta documentación de soporte',
        )

    def test_informe_rechazado_aparece_con_motivo_y_observacion(self):
        self._crear_informe_rechazado()

        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin
        )

        self.assertEqual(len(datos['rechazados']), 1)

        rechazado = datos['rechazados'][0]

        self.assertEqual(
            rechazado['tipo_rechazo'],
            'Documentación incompleta',
        )

        self.assertEqual(
            rechazado['observacion'],
            'El informe no contiene las evidencias requeridas',
        )

    def test_propuesta_reactivada_no_aparece_como_rechazada(self):
        propuesta = self._crear_propuesta_rechazada()

        propuesta.estado = EstadoTramite.REQUIERE_MODIFICACION
        propuesta.save(update_fields=['estado'])

        HistorialEstado.objects.create(
            propuesta=propuesta,
            usuario=self.usuario_admin,
            estado_anterior=EstadoTramite.RECHAZADO,
            estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
            tipo_accion='Reactivacion',
            observacion='Propuesta reactivada para correcciones',
            fecha_hora=timezone.now(),
        )

        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin
        )

        self.assertEqual(len(datos['rechazados']), 0)

    def test_informe_reactivado_no_aparece_como_rechazado(self):
        informe = self._crear_informe_rechazado()

        informe.estado = EstadoTramite.REQUIERE_MODIFICACION
        informe.save(update_fields=['estado'])

        HistorialEstado.objects.create(
            informe=informe,
            usuario=self.usuario_admin,
            estado_anterior=EstadoTramite.RECHAZADO,
            estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
            tipo_accion='Reactivacion',
            observacion='Informe reactivado para correcciones',
            fecha_hora=timezone.now(),
        )

        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin
        )

        self.assertEqual(len(datos['rechazados']), 0)

    def test_rango_fechas_filtra_por_fecha_de_decision(self):
        Informe.objects.update(
            fecha_envio=timezone.now().replace(year=2000)
        )

        hoy = timezone.localdate()

        datos = obtener_datos_reporte_trabajo_social(
            self.usuario_admin,
            date_start=hoy,
            date_end=hoy,
        )

        self.assertEqual(len(datos['aprobados']), 2)

    def test_descarga_exitosa_genera_pdf_y_registra_auditoria(self):
        self.client.force_login(self.usuario_admin)

        hoy = timezone.localdate()

        respuesta = self.client.post(
            reverse('reportes:reportes'),
            {
                'filterDateStart': hoy.replace(day=1).isoformat(),
                'filterDateEnd': hoy.isoformat(),
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta['Content-Type'],
            'application/pdf',
        )
        self.assertTrue(
            respuesta['Content-Disposition'].startswith('attachment;')
        )
        contenido_pdf = b"".join(respuesta.streaming_content)
        self.assertTrue(contenido_pdf.startswith(b"%PDF"))

        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.usuario_admin,
                accion='reporte_descarga',
                resultado='Éxito',
            ).exists()
        )

    def test_descarga_sin_registros_muestra_mensaje_y_audita_fallo(self):
        self.client.force_login(self.usuario_admin)

        respuesta = self.client.post(
            reverse('reportes:reportes'),
            {
                'filterDateStart': '2000-01-01',
                'filterDateEnd': '2000-01-02',
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            'No se encontraron registros',
        )

        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.usuario_admin,
                accion='reporte_descarga',
                resultado='Fallo',
                detalle__contains='No se encontraron registros',
            ).exists()
        )

    def test_fechas_invalidas_no_generan_pdf(self):
        self.client.force_login(self.usuario_admin)

        with patch(
            'apps.reportes.views.reportes.generar_pdf_trabajo_social'
        ) as generar_pdf:
            respuesta = self.client.post(
                reverse('reportes:reportes'),
                {
                    'filterDateStart': '2026-12-31',
                    'filterDateEnd': '2026-01-01',
                },
            )

        self.assertEqual(respuesta.status_code, 200)
        generar_pdf.assert_not_called()
        self.assertContains(respuesta, 'no puede ser posterior')

    def test_error_al_generar_pdf_registra_fallo(self):
        self.client.force_login(self.usuario_admin)

        hoy = timezone.localdate()

        with patch(
            'apps.reportes.views.reportes.generar_pdf_trabajo_social',
            side_effect=Exception('Error simulado'),
        ):
            respuesta = self.client.post(
                reverse('reportes:reportes'),
                {
                    'filterDateStart': hoy.replace(day=1).isoformat(),
                    'filterDateEnd': hoy.isoformat(),
                },
            )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            'Ocurrió un error al generar el reporte',
        )

        self.assertTrue(
            Auditoria.objects.filter(
                usuario=self.usuario_admin,
                accion='reporte_descarga',
                resultado='Fallo',
                detalle__contains='Error al generar el reporte',
            ).exists()
        )