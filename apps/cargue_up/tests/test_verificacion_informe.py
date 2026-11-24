"""SISTRA-09 · Notificación de cargue UP – Director (informe): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test apps.cargue_up.tests.test_verificacion_informe
"""

from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.forms.verificacion_informe import (
    ACCION_AUDITORIA_REAPERTURA,
    MSG_09_01,
    MSG_09_02,
    MSG_09_04,
    MSG_09_05,
    MSG_09_CORRECCION,
    MSG_09_CORRECCION_NO_DISPONIBLE,
    MSG_09_ERROR,
    resultado_de_correccion,
)
from apps.cargue_up.models import CargueUp, EstadoVerificacion, HistorialCargueUp
from apps.informes.models import Informe
from apps.parametrizacion.models import Carrera, EstadoPeriodo, Facultad, PeriodoAcademico
from apps.personas.models import Director, DirectorCarrera, Estudiante, EstudianteCarrera
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Permiso, Rol, RolPermiso

CLAVE = 'ClavePruebas2026!'
APROBADO_UP = EstadoVerificacion.APROBADO_EN_UP
RECHAZADO_UP = EstadoVerificacion.RECHAZADO_EN_UP


class BaseVerificacionTests(TestCase):
    """Un Director con una carrera, estudiantes propios y uno ajeno."""

    @classmethod
    def setUpTestData(cls):
        cls.Usuario = get_user_model()
        cls.rol_director = Rol.objects.get(nombre='Director')
        cls.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        cls.rol_admin = Rol.objects.get(nombre='Administrador')

        facultad = Facultad.objects.create(nombre='Facultad SISTRA-09')
        cls.carrera = Carrera.objects.create(facultad=facultad, nombre='Carrera propia', codigo='S09-A')
        cls.carrera_ajena = Carrera.objects.create(facultad=facultad, nombre='Carrera ajena', codigo='S09-B')
        cls.periodo = PeriodoAcademico.objects.create(
            nombre='2026-S09',
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 6, 30),
            fecha_cierre_propuesta=date(2026, 3, 1),
            fecha_cierre_informe=date(2026, 6, 1),
            estado=EstadoPeriodo.CERRADO,
        )

        cls.director = cls._usuario('director', cls.rol_director, '9000001')
        cls.director_nuevo = cls._usuario('director2', cls.rol_director, '9000002')
        cls.director_ajeno = cls._usuario('director3', cls.rol_director, '9000004')
        cls.administrador = cls._usuario('admin', cls.rol_admin, '9000003')
        cls.perfil_director = Director.objects.create(usuario=cls.director)
        cls.perfil_nuevo = Director.objects.create(usuario=cls.director_nuevo)
        perfil_ajeno = Director.objects.create(usuario=cls.director_ajeno)
        cls.asignacion = DirectorCarrera.objects.create(
            director=cls.perfil_director, carrera=cls.carrera,
            fecha_inicio=timezone.localdate(), activo=True,
        )
        DirectorCarrera.objects.create(
            director=perfil_ajeno, carrera=cls.carrera_ajena,
            fecha_inicio=timezone.localdate(), activo=True,
        )

    @classmethod
    def _usuario(cls, alias, rol, cedula, nombre=None):
        return cls.Usuario.objects.create_user(
            correo_institucional=f'{alias}@example.com',
            nombre=nombre or f'Usuario {alias}',
            cedula=cedula,
            nombre_usuario=f'{alias}_s09',
            password=CLAVE,
            rol=rol,
            requiere_cambio_contrasena=False,
        )

    @classmethod
    def crear_informe(cls, alias, estado=EstadoTramite.SUBIDO_EN_UP, carrera=None, nombre=None,
                      cedula=None, con_cargue=True):
        """Informe del estudiante; con cargue pendiente si está en Subido en UP."""
        usuario = cls._usuario(
            alias, cls.rol_estudiante, cedula or f'8{abs(hash(alias)) % 10**8:08d}', nombre
        )
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=Estudiante.objects.create(usuario=usuario),
            carrera=carrera or cls.carrera,
            estado='Activo',
        )
        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion, fecha_inicio=timezone.now(), estado='En curso'
        )
        propuesta = Propuesta.objects.create(
            proceso=proceso, periodo_academico=cls.periodo, codigo=f'PROP-{alias}',
            titulo=f'Titulo {alias}', estado=EstadoTramite.APROBADO_EN_UP,
        )
        informe = Informe.objects.create(
            propuesta=propuesta, periodo_academico=cls.periodo, codigo=f'INF-{alias}', estado=estado,
        )
        if con_cargue and estado == EstadoTramite.SUBIDO_EN_UP:
            CargueUp.objects.create(informe=informe, fecha_declaracion=timezone.now() - timedelta(hours=1))
        return informe

    @classmethod
    def verificar_directo(cls, informe, resultado, observacion='', director=None):
        """Deja el informe como si el Director ya hubiera decidido (para probar correcciones)."""
        cargue = informe.cargues_up.order_by('-fecha_declaracion', '-pk').first()
        cargue.estado_verificacion = resultado
        cargue.director = director or cls.perfil_director
        cargue.fecha_verificacion = timezone.now()
        cargue.observacion = observacion
        cargue.save()
        informe.estado = APROBADO_UP if resultado == APROBADO_UP else EstadoTramite.APROBADO
        informe.save()
        return cargue

    def entrar_como_director(self):
        self.client.force_login(self.director)

    @property
    def url_lista(self):
        return reverse('cargue_up:verificacion_informe_lista')

    def url_detalle(self, informe):
        return reverse('cargue_up:verificacion_informe_detalle', args=[informe.pk])

    def url_decidir(self, informe):
        return reverse('cargue_up:verificacion_informe_decidir', args=[informe.pk])

    def url_corregir(self, informe):
        return reverse('cargue_up:verificacion_informe_corregir', args=[informe.pk])

    def ultimo_cargue(self, informe):
        return informe.cargues_up.order_by('-fecha_declaracion', '-pk').first()

    def decidir(self, informe, resultado, observacion='', id_cargue=None):
        return self.client.post(
            self.url_decidir(informe),
            {
                'resultado': resultado,
                'id_cargue': id_cargue or self.ultimo_cargue(informe).pk,
                'observacion': observacion,
            },
            follow=True,
        )

    def corregir(self, informe, motivo='', observacion='', id_cargue=None, resultado=None):
        cargue = self.ultimo_cargue(informe)
        if resultado is None and cargue:
            resultado = resultado_de_correccion(informe.estado, cargue.estado_verificacion)
        datos = {
            'id_cargue': id_cargue or (cargue.pk if cargue else None),
            'motivo': motivo,
            'observacion': observacion,
        }
        if resultado is not None:
            datos['resultado'] = resultado
        return self.client.post(
            self.url_corregir(informe),
            datos,
            follow=True,
        )

    def mensajes(self, respuesta):
        return [str(m) for m in respuesta.context['messages']]


class AccesoTests(BaseVerificacionTests):
    def test_sin_sesion_redirige_al_login_y_no_guarda(self):
        informe = self.crear_informe('sinsesion')
        respuesta = self.client.post(
            self.url_decidir(informe),
            {'resultado': APROBADO_UP, 'id_cargue': self.ultimo_cargue(informe).pk},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn('next=', respuesta.url)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_estudiante_recibe_403_y_queda_auditado(self):
        informe = self.crear_informe('est403')
        usuario = informe.propuesta.proceso.estudiante_carrera.estudiante.usuario
        self.client.force_login(usuario)

        self.assertEqual(self.client.get(self.url_lista).status_code, 403)
        respuesta = self.client.post(self.url_decidir(informe), {'resultado': APROBADO_UP, 'id_cargue': 1})
        self.assertEqual(respuesta.status_code, 403)

        auditoria = Auditoria.objects.filter(accion='intento_verificacion_informe')
        self.assertEqual(auditoria.count(), 2)
        self.assertTrue(all(a.resultado == 'Bloqueado' and a.usuario == usuario for a in auditoria))
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_administrador_no_verifica(self):
        informe = self.crear_informe('adm')
        self.client.force_login(self.administrador)
        self.assertEqual(self.client.get(self.url_lista).status_code, 403)
        self.assertEqual(self.client.post(self.url_decidir(informe), {}).status_code, 403)

    def test_director_sin_permiso_no_verifica(self):
        RolPermiso.objects.filter(
            rol=self.rol_director, permiso=Permiso.objects.get(nombre='informe.aprobar')
        ).delete()
        self.entrar_como_director()
        self.assertEqual(self.client.get(self.url_lista).status_code, 403)

    def test_director_sin_asignacion_activa_no_verifica(self):
        self.asignacion.activo = False
        self.asignacion.save(update_fields=['activo'])
        self.entrar_como_director()
        self.assertEqual(self.client.get(self.url_lista).status_code, 403)

    def test_decidir_solo_acepta_post(self):
        informe = self.crear_informe('get')
        self.entrar_como_director()
        self.assertEqual(self.client.get(self.url_decidir(informe)).status_code, 405)
        self.assertEqual(self.client.get(self.url_corregir(informe)).status_code, 405)

    def test_estado_vacio(self):
        self.entrar_como_director()
        respuesta = self.client.get(self.url_lista)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'No tienes informes por verificar.')


class AlcanceDelDirectorTests(BaseVerificacionTests):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.propio = cls.crear_informe('propio', nombre='Estudiante Propio', cedula='7000001')
        cls.ajeno = cls.crear_informe('ajeno', carrera=cls.carrera_ajena, nombre='Estudiante Ajeno', cedula='7000002')

    def test_lista_solo_muestra_subido_en_up_de_sus_estudiantes(self):
        self.crear_informe('aprobado', EstadoTramite.APROBADO, nombre='Ya Aprobado')
        self.crear_informe('revision', EstadoTramite.EN_REVISION, nombre='En Revision')
        self.entrar_como_director()
        respuesta = self.client.get(self.url_lista)
        self.assertContains(respuesta, 'Estudiante Propio')
        for ausente in ('Estudiante Ajeno', 'Ya Aprobado', 'En Revision'):
            self.assertNotContains(respuesta, ausente)

    def test_lista_muestra_fecha_del_aviso_y_acciones(self):
        self.entrar_como_director()
        respuesta = self.client.get(self.url_lista)
        for texto in ('Ver detalle', 'Aprobado en UP', 'Rechazado en UP', '7000001', 'Titulo propio'):
            self.assertContains(respuesta, texto)
        fecha = self.ultimo_cargue(self.propio).fecha_declaracion
        self.assertContains(respuesta, timezone.localtime(fecha).strftime('%d/%m/%Y %H:%M'))

    def test_busqueda_por_nombre_o_cedula(self):
        self.crear_informe('maria', nombre='Maria Propia', cedula='7000009')
        self.entrar_como_director()
        self.assertContains(self.client.get(self.url_lista, {'buscar': 'Maria'}), 'Maria Propia')
        self.assertNotContains(self.client.get(self.url_lista, {'buscar': 'Maria'}), 'Estudiante Propio')
        self.assertContains(self.client.get(self.url_lista, {'buscar': '7000001'}), 'Estudiante Propio')
        # La búsqueda nunca saca de su alcance a estudiantes ajenos.
        self.assertNotContains(self.client.get(self.url_lista, {'buscar': 'Ajeno'}), 'Estudiante Ajeno')

    def test_detalle_ajeno_responde_404_sin_datos_y_se_audita(self):
        self.entrar_como_director()
        respuesta = self.client.get(self.url_detalle(self.ajeno))
        self.assertEqual(respuesta.status_code, 404)
        self.assertNotContains(respuesta, 'Estudiante Ajeno', status_code=404)
        auditoria = Auditoria.objects.get(accion='intento_verificacion_informe')
        self.assertEqual(auditoria.id_registro_afectado, self.ajeno.pk)
        self.assertNotIn('Estudiante Ajeno', auditoria.detalle)

    def test_decidir_y_corregir_sobre_ajeno_no_cambian_nada(self):
        self.entrar_como_director()
        cargue = self.ultimo_cargue(self.ajeno)
        respuesta = self.client.post(
            self.url_decidir(self.ajeno), {'resultado': APROBADO_UP, 'id_cargue': cargue.pk}
        )
        self.assertEqual(respuesta.status_code, 404)
        respuesta = self.client.post(
            self.url_corregir(self.ajeno), {'id_cargue': cargue.pk, 'motivo': 'x'}
        )
        self.assertEqual(respuesta.status_code, 404)
        self.ajeno.refresh_from_db()
        cargue.refresh_from_db()
        self.assertEqual(self.ajeno.estado, EstadoTramite.SUBIDO_EN_UP)
        self.assertEqual(cargue.estado_verificacion, EstadoVerificacion.PENDIENTE)
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_informe_inexistente_responde_igual_que_ajeno(self):
        self.entrar_como_director()
        url = reverse('cargue_up:verificacion_informe_detalle', args=[999999])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_al_perder_la_asignacion_deja_de_ver_y_decidir(self):
        self.entrar_como_director()
        self.assertEqual(self.client.get(self.url_detalle(self.propio)).status_code, 200)
        self.asignacion.activo = False
        self.asignacion.save(update_fields=['activo'])
        self.assertEqual(self.client.get(self.url_detalle(self.propio)).status_code, 403)
        respuesta = self.client.post(
            self.url_decidir(self.propio),
            {'resultado': APROBADO_UP, 'id_cargue': self.ultimo_cargue(self.propio).pk},
        )
        self.assertEqual(respuesta.status_code, 403)
        self.propio.refresh_from_db()
        self.assertEqual(self.propio.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_la_lista_se_limita_por_servidor_aunque_se_manipule_la_url(self):
        self.entrar_como_director()
        respuesta = self.client.get(self.url_lista, {'vista': 'pendientes', 'carrera': self.carrera_ajena.pk})
        self.assertNotContains(respuesta, 'Estudiante Ajeno')


class AprobarTests(BaseVerificacionTests):
    def test_aprobado_en_up_cambia_estado_avisa_y_audita(self):
        informe = self.crear_informe('apr', nombre='Ana Aprobada')
        cargue = self.ultimo_cargue(informe)
        self.entrar_como_director()

        respuesta = self.decidir(informe, APROBADO_UP)

        self.assertRedirects(respuesta, self.url_lista)
        self.assertIn(MSG_09_01, self.mensajes(respuesta))
        informe.refresh_from_db()
        cargue.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO_EN_UP)
        self.assertEqual(cargue.estado_verificacion, APROBADO_UP)
        self.assertEqual(cargue.director, self.perfil_director)
        self.assertGreaterEqual(cargue.fecha_verificacion, cargue.fecha_declaracion)

        historial = HistorialEstado.objects.get(informe=informe)
        self.assertEqual(
            (historial.estado_anterior, historial.estado_nuevo, historial.usuario),
            (EstadoTramite.SUBIDO_EN_UP, EstadoTramite.APROBADO_EN_UP, self.director),
        )
        aviso = Notificacion.objects.get(informe=informe)
        self.assertEqual(aviso.usuario, informe.propuesta.proceso.estudiante_carrera.estudiante.usuario)
        self.assertIn('Aprobado en UP', aviso.mensaje)
        self.assertIsNone(aviso.fecha_lectura)
        auditoria = Auditoria.objects.get(accion='verificacion_informe')
        self.assertEqual((auditoria.usuario, auditoria.resultado), (self.director, 'Éxito'))
        self.assertEqual(auditoria.id_registro_afectado, informe.pk)

    def test_aprobar_ignora_observacion_enviada(self):
        informe = self.crear_informe('aprobs')
        self.entrar_como_director()
        self.decidir(informe, APROBADO_UP, observacion='texto que no aplica')
        self.assertEqual(self.ultimo_cargue(informe).observacion, '')

    def test_el_informe_verificado_sale_de_la_lista(self):
        informe = self.crear_informe('sale', nombre='Sale De Lista')
        self.entrar_como_director()
        self.decidir(informe, APROBADO_UP)
        self.assertNotContains(self.client.get(self.url_lista), 'Sale De Lista')


class RechazarTests(BaseVerificacionTests):
    def test_rechazado_exige_observacion(self):
        informe = self.crear_informe('rec0')
        self.entrar_como_director()
        for observacion in ('', '   '):
            respuesta = self.decidir(informe, RECHAZADO_UP, observacion)
            self.assertEqual(respuesta.status_code, 400)
            self.assertContains(respuesta, MSG_09_05, status_code=400)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)
        self.assertEqual(Notificacion.objects.count(), 0)
        self.assertEqual(HistorialEstado.objects.count(), 0)

    def test_observacion_no_admite_html(self):
        informe = self.crear_informe('rec1')
        self.entrar_como_director()
        respuesta = self.decidir(informe, RECHAZADO_UP, '<script>alert(1)</script>')
        self.assertEqual(respuesta.status_code, 400)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_observacion_no_pasa_de_mil_caracteres(self):
        informe = self.crear_informe('rec2')
        self.entrar_como_director()
        self.assertEqual(self.decidir(informe, RECHAZADO_UP, 'a' * 1001).status_code, 400)

    def test_rechazado_devuelve_a_aprobado_y_avisa_con_la_observacion(self):
        informe = self.crear_informe('rec')
        self.entrar_como_director()

        respuesta = self.decidir(informe, RECHAZADO_UP, 'El archivo no es el aprobado')

        self.assertIn(MSG_09_02, self.mensajes(respuesta))
        informe.refresh_from_db()
        cargue = self.ultimo_cargue(informe)
        self.assertEqual(informe.estado, EstadoTramite.APROBADO)
        self.assertEqual(cargue.estado_verificacion, RECHAZADO_UP)
        self.assertEqual(cargue.observacion, 'El archivo no es el aprobado')
        aviso = Notificacion.objects.get(informe=informe)
        self.assertIn('lo cargado no coincide', aviso.mensaje)
        self.assertIn('El archivo no es el aprobado', aviso.mensaje)
        historial = HistorialEstado.objects.get(informe=informe)
        self.assertEqual(historial.estado_nuevo, EstadoTramite.APROBADO)
        self.assertEqual(historial.observacion, 'El archivo no es el aprobado')

    def test_tras_rechazar_el_estudiante_puede_cargar_de_nuevo(self):
        informe = self.crear_informe('recarga', nombre='Recarga Estudiante')
        self.entrar_como_director()
        self.decidir(informe, RECHAZADO_UP, 'No coincide')
        # El estudiante vuelve a pulsar «Subido en UP» (SISTRA-08): nuevo cargue pendiente.
        informe.refresh_from_db()
        informe.estado = EstadoTramite.SUBIDO_EN_UP
        informe.save()
        CargueUp.objects.create(informe=informe, fecha_declaracion=timezone.now())
        self.assertContains(self.client.get(self.url_lista), 'Recarga Estudiante')
        self.assertEqual(informe.cargues_up.count(), 2)


class EstadoYRepeticionTests(BaseVerificacionTests):
    def test_solo_se_verifica_un_informe_en_subido_en_up(self):
        for alias, estado in [
            ('a', EstadoTramite.APROBADO),
            ('b', EstadoTramite.EN_REVISION),
            ('c', EstadoTramite.APROBADO_EN_UP),
        ]:
            informe = self.crear_informe(alias, estado)
            CargueUp.objects.create(informe=informe)
            self.entrar_como_director()
            respuesta = self.decidir(informe, APROBADO_UP, id_cargue=self.ultimo_cargue(informe).pk)
            self.assertIn(MSG_09_04, self.mensajes(respuesta))
            informe.refresh_from_db()
            self.assertEqual(informe.estado, estado)
        self.assertEqual(Notificacion.objects.count(), 0)
        self.assertEqual(HistorialEstado.objects.count(), 0)

    def test_doble_clic_registra_una_sola_decision(self):
        informe = self.crear_informe('doble')
        self.entrar_como_director()
        id_cargue = self.ultimo_cargue(informe).pk
        primera = self.decidir(informe, APROBADO_UP, id_cargue=id_cargue)
        segunda = self.decidir(informe, APROBADO_UP, id_cargue=id_cargue)
        self.assertIn(MSG_09_01, self.mensajes(primera))
        self.assertIn(MSG_09_04, self.mensajes(segunda))
        self.assertEqual(Notificacion.objects.filter(informe=informe).count(), 1)
        self.assertEqual(HistorialEstado.objects.filter(informe=informe).count(), 1)
        self.assertEqual(Auditoria.objects.filter(accion='verificacion_informe').count(), 1)
        self.assertEqual(informe.cargues_up.count(), 1)

    def test_decisiones_contradictorias_seguidas_solo_cuenta_la_primera(self):
        informe = self.crear_informe('contra')
        self.entrar_como_director()
        id_cargue = self.ultimo_cargue(informe).pk
        self.decidir(informe, APROBADO_UP, id_cargue=id_cargue)
        respuesta = self.decidir(informe, RECHAZADO_UP, 'tarde', id_cargue=id_cargue)
        self.assertIn(MSG_09_04, self.mensajes(respuesta))
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO_EN_UP)

    def test_pantalla_desactualizada_no_decide_sobre_un_cargue_nuevo(self):
        informe = self.crear_informe('viejo')
        id_visto = self.ultimo_cargue(informe).pk
        nuevo = CargueUp.objects.create(informe=informe, fecha_declaracion=timezone.now())
        self.entrar_como_director()
        respuesta = self.decidir(informe, APROBADO_UP, id_cargue=id_visto)
        self.assertIn(MSG_09_04, self.mensajes(respuesta))
        nuevo.refresh_from_db()
        self.assertEqual(nuevo.estado_verificacion, EstadoVerificacion.PENDIENTE)

    def test_resultado_invalido_no_guarda(self):
        informe = self.crear_informe('inval')
        self.entrar_como_director()
        respuesta = self.decidir(informe, 'Pendiente')
        self.assertEqual(respuesta.status_code, 400)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_subido_en_up_sin_cargue_pendiente_no_se_lista_ni_se_decide(self):
        informe = self.crear_informe('incoherente', con_cargue=False)
        self.entrar_como_director()
        self.assertNotContains(self.client.get(self.url_lista), informe.codigo)
        respuesta = self.client.post(
            self.url_decidir(informe), {'resultado': APROBADO_UP, 'id_cargue': 1}, follow=True
        )
        self.assertIn(MSG_09_04, self.mensajes(respuesta))
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)


class FalloDePersistenciaTests(BaseVerificacionTests):
    def test_si_falla_el_aviso_no_queda_nada_a_medias(self):
        informe = self.crear_informe('falla')
        self.entrar_como_director()
        with mock.patch.object(Notificacion.objects, 'create', side_effect=RuntimeError('simulado')):
            with self.assertLogs('apps.cargue_up.views.verificacion_informe', level='ERROR'):
                respuesta = self.decidir(informe, APROBADO_UP)

        self.assertIn(MSG_09_ERROR, self.mensajes(respuesta))
        informe.refresh_from_db()
        cargue = self.ultimo_cargue(informe)
        self.assertEqual(informe.estado, EstadoTramite.SUBIDO_EN_UP)
        self.assertEqual(cargue.estado_verificacion, EstadoVerificacion.PENDIENTE)
        self.assertIsNone(cargue.director)
        self.assertEqual(HistorialEstado.objects.count(), 0)
        self.assertEqual(Notificacion.objects.count(), 0)
        self.assertFalse(Auditoria.objects.filter(accion='verificacion_informe', resultado='Éxito').exists())
        fallo = Auditoria.objects.get(accion='verificacion_informe', resultado='Fallo')
        self.assertNotIn('simulado', fallo.detalle)

    def test_tras_un_fallo_se_puede_reintentar(self):
        informe = self.crear_informe('reintento')
        self.entrar_como_director()
        with mock.patch.object(Notificacion.objects, 'create', side_effect=RuntimeError('x')):
            with self.assertLogs('apps.cargue_up.views.verificacion_informe', level='ERROR'):
                self.decidir(informe, APROBADO_UP)
        respuesta = self.decidir(informe, APROBADO_UP)
        self.assertIn(MSG_09_01, self.mensajes(respuesta))
        self.assertEqual(Notificacion.objects.filter(informe=informe).count(), 1)

    def test_un_fallo_de_auditoria_no_oculta_el_404(self):
        informe = self.crear_informe('audit', carrera=self.carrera_ajena)
        self.entrar_como_director()
        with mock.patch.object(Auditoria.objects, 'create', side_effect=RuntimeError('falla')):
            with self.assertLogs('apps.cargue_up.views.verificacion_informe', level='ERROR'):
                respuesta = self.client.get(self.url_detalle(informe))
        self.assertEqual(respuesta.status_code, 404)


class CorreccionTests(BaseVerificacionTests):
    def test_corregir_aprobado_a_rechazado_conserva_la_decision_anterior(self):
        informe = self.crear_informe('corr1')
        cargue = self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()
        cargues_antes = informe.cargues_up.count()

        respuesta = self.corregir(informe, motivo='Me equivoqué de archivo', observacion='No coincide')

        self.assertIn(MSG_09_CORRECCION, self.mensajes(respuesta))
        informe.refresh_from_db()
        cargue.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO)
        self.assertEqual(cargue.estado_verificacion, RECHAZADO_UP)
        self.assertEqual(informe.cargues_up.count(), cargues_antes)  # no hay nuevo intento
        historial = HistorialCargueUp.objects.get(cargue_up=cargue)
        self.assertEqual(
            (historial.estado_anterior, historial.estado_nuevo, historial.motivo_correccion,
             historial.observacion, historial.director),
            (APROBADO_UP, RECHAZADO_UP, 'Me equivoqué de archivo', 'No coincide', self.perfil_director),
        )
        aviso = Notificacion.objects.get(informe=informe)
        self.assertIn('corrigió', aviso.mensaje)
        self.assertIn('No coincide', aviso.mensaje)
        self.assertTrue(Auditoria.objects.filter(accion='correccion_verif_informe', resultado='Éxito').exists())

    def test_corregir_rechazado_a_aprobado(self):
        informe = self.crear_informe('corr2')
        cargue = self.verificar_directo(informe, RECHAZADO_UP, 'Antes no coincidía')
        self.entrar_como_director()

        respuesta = self.corregir(informe, motivo='Sí coincidía')

        self.assertIn(MSG_09_CORRECCION, self.mensajes(respuesta))
        informe.refresh_from_db()
        cargue.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO_EN_UP)
        self.assertEqual(cargue.estado_verificacion, APROBADO_UP)
        self.assertEqual(HistorialCargueUp.objects.filter(cargue_up=cargue).count(), 1)
        auditoria = Auditoria.objects.get(accion='correccion_verif_informe')
        self.assertIn('Antes no coincidía', auditoria.detalle)  # la observación anterior queda auditada

    def test_la_correccion_exige_motivo_y_observacion_si_rechaza(self):
        informe = self.crear_informe('corr3')
        self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()
        for motivo, observacion in [('', 'obs'), ('motivo', ''), ('', '')]:
            respuesta = self.corregir(informe, motivo=motivo, observacion=observacion)
            self.assertEqual(respuesta.status_code, 400)
            self.assertContains(respuesta, MSG_09_05, status_code=400)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO_EN_UP)
        self.assertEqual(HistorialCargueUp.objects.count(), 0)
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_no_se_corrige_si_el_estudiante_ya_cargo_de_nuevo(self):
        informe = self.crear_informe('corr4')
        anterior = self.verificar_directo(informe, RECHAZADO_UP, 'No coincide')
        informe.estado = EstadoTramite.SUBIDO_EN_UP
        informe.save()
        CargueUp.objects.create(informe=informe, fecha_declaracion=timezone.now())
        self.entrar_como_director()
        respuesta = self.corregir(informe, motivo='x', id_cargue=anterior.pk)
        self.assertIn(MSG_09_CORRECCION_NO_DISPONIBLE, self.mensajes(respuesta))
        anterior.refresh_from_db()
        self.assertEqual(anterior.estado_verificacion, RECHAZADO_UP)
        self.assertEqual(HistorialCargueUp.objects.count(), 0)

    def test_no_se_corrige_un_informe_pendiente(self):
        informe = self.crear_informe('corr5')
        self.entrar_como_director()
        respuesta = self.corregir(informe, motivo='x')
        self.assertIn(MSG_09_CORRECCION_NO_DISPONIBLE, self.mensajes(respuesta))

    def test_el_director_actual_corrige_la_verificacion_de_un_director_anterior(self):
        informe = self.crear_informe('corr6')
        self.verificar_directo(informe, APROBADO_UP, director=self.perfil_director)
        DirectorCarrera.objects.filter(pk=self.asignacion.pk).update(activo=False)
        DirectorCarrera.objects.create(
            director=self.perfil_nuevo, carrera=self.carrera,
            fecha_inicio=timezone.localdate(), activo=True,
        )
        self.client.force_login(self.director_nuevo)
        respuesta = self.corregir(informe, motivo='Corrijo al anterior', observacion='No coincide')
        self.assertIn(MSG_09_CORRECCION, self.mensajes(respuesta))
        historial = HistorialCargueUp.objects.get()
        self.assertEqual(historial.director, self.perfil_nuevo)

    def test_pestana_verificados_ofrece_corregir_y_detalle_muestra_historial(self):
        informe = self.crear_informe('corr7', nombre='Ya Verificada')
        self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()
        self.assertContains(self.client.get(self.url_lista, {'vista': 'verificados'}), 'Corregir verificación')
        self.assertNotContains(self.client.get(self.url_lista), 'Ya Verificada')
        self.assertContains(self.client.get(self.url_detalle(informe)), 'Historial de cargues y verificaciones')

    def test_un_fallo_en_la_correccion_revierte_todo(self):
        informe = self.crear_informe('corr8')
        cargue = self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()
        with mock.patch.object(Notificacion.objects, 'create', side_effect=RuntimeError('x')):
            with self.assertLogs('apps.cargue_up.views.verificacion_informe', level='ERROR'):
                respuesta = self.corregir(informe, motivo='m', observacion='o')
        self.assertIn(MSG_09_ERROR, self.mensajes(respuesta))
        informe.refresh_from_db()
        cargue.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO_EN_UP)
        self.assertEqual(cargue.estado_verificacion, APROBADO_UP)
        self.assertEqual(HistorialCargueUp.objects.count(), 0)

    def test_envio_duplicado_de_correccion_es_rechazado_y_no_duplica(self):
        informe = self.crear_informe('corr_dup')
        cargue = self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()

        # Primer envío de la corrección
        respuesta1 = self.corregir(
            informe, motivo='Error de archivo', observacion='No coincide', resultado=RECHAZADO_UP
        )
        self.assertIn(MSG_09_CORRECCION, self.mensajes(respuesta1))

        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO)
        self.assertEqual(HistorialCargueUp.objects.filter(cargue_up=cargue).count(), 1)
        self.assertEqual(Notificacion.objects.filter(informe=informe).count(), 1)

        # Segundo envío con los mismos datos originales (intento duplicado)
        respuesta2 = self.client.post(
            self.url_corregir(informe),
            {
                'id_cargue': cargue.pk,
                'resultado': RECHAZADO_UP,
                'motivo': 'Error de archivo',
                'observacion': 'No coincide',
            },
            follow=True,
        )
        self.assertIn(MSG_09_CORRECCION_NO_DISPONIBLE, self.mensajes(respuesta2))

        # El informe no debe revertirse a Aprobado en UP por el segundo envío
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO)
        self.assertEqual(HistorialCargueUp.objects.filter(cargue_up=cargue).count(), 1)
        self.assertEqual(Notificacion.objects.filter(informe=informe).count(), 1)

    def test_reapertura_proceso_cuando_estudiante_ya_finalizo(self):
        informe = self.crear_informe('corr_reap')
        proceso = informe.propuesta.proceso
        proceso.estado = EstadoAvance.FINALIZADA
        proceso.fecha_finalizacion = timezone.now()
        proceso.save(update_fields=['estado', 'fecha_finalizacion'])

        cargue = self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()

        respuesta = self.corregir(
            informe,
            motivo='Revisión posterior detectó inconsistencia',
            observacion='El informe final no coincide con la versión física',
            resultado=RECHAZADO_UP,
        )
        self.assertIn(MSG_09_CORRECCION, self.mensajes(respuesta))

        # Verificar que el proceso cambió a En curso y fecha_finalizacion es None
        proceso.refresh_from_db()
        self.assertEqual(proceso.estado, EstadoAvance.EN_CURSO)
        self.assertIsNone(proceso.fecha_finalizacion)

        # Verificar registro de auditoría de reapertura
        auditoria_reap = Auditoria.objects.get(accion=ACCION_AUDITORIA_REAPERTURA)
        self.assertEqual(auditoria_reap.resultado, 'Éxito')
        self.assertEqual(auditoria_reap.tabla_afectada, 'proceso_trabajo_social')
        self.assertEqual(auditoria_reap.id_registro_afectado, proceso.pk)
        self.assertIn('Finalizada -> En curso', auditoria_reap.detalle)
        self.assertIn('reapertura', auditoria_reap.detalle)

        # Verificar notificación con aviso de reapertura
        aviso = Notificacion.objects.get(informe=informe)
        self.assertIn('tu proceso fue reabierto', aviso.mensaje)
        self.assertIn('vuelve a cargar el informe en UP', aviso.mensaje)

    def test_correccion_rechazo_proceso_no_finalizado_no_reabre(self):
        informe = self.crear_informe('corr_no_reap')
        proceso = informe.propuesta.proceso
        self.assertEqual(proceso.estado, EstadoAvance.EN_CURSO)
        self.assertIsNone(proceso.fecha_finalizacion)

        cargue = self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()

        respuesta = self.corregir(
            informe,
            motivo='Corrección habitual',
            observacion='No coincide',
            resultado=RECHAZADO_UP,
        )
        self.assertIn(MSG_09_CORRECCION, self.mensajes(respuesta))

        proceso.refresh_from_db()
        self.assertEqual(proceso.estado, EstadoAvance.EN_CURSO)
        self.assertIsNone(proceso.fecha_finalizacion)

        # No se debe registrar auditoría de reapertura
        self.assertFalse(Auditoria.objects.filter(accion=ACCION_AUDITORIA_REAPERTURA).exists())

        # Notificación no contiene texto de reapertura
        aviso = Notificacion.objects.get(informe=informe)
        self.assertNotIn('reabierto', aviso.mensaje)


class PantallaTests(BaseVerificacionTests):
    def test_detalle_ofrece_las_dos_decisiones_cuando_esta_pendiente(self):
        informe = self.crear_informe('pant')
        self.entrar_como_director()
        respuesta = self.client.get(self.url_detalle(informe))
        self.assertTemplateUsed(respuesta, 'cargue_up/verificacion_informe/detalle.html')
        self.assertContains(respuesta, 'Confirmar Aprobado en UP')
        self.assertContains(respuesta, 'Confirmar Rechazado en UP')

    def test_detalle_de_un_informe_ya_verificado_no_ofrece_decidir(self):
        informe = self.crear_informe('pant2')
        self.verificar_directo(informe, APROBADO_UP)
        self.entrar_como_director()
        respuesta = self.client.get(self.url_detalle(informe))
        self.assertNotContains(respuesta, 'Confirmar Aprobado en UP')

    def test_la_lista_no_expone_datos_de_otros_directores(self):
        self.crear_informe('mio', nombre='Estudiante Mio')
        self.crear_informe('otro', carrera=self.carrera_ajena, nombre='Estudiante De Otro')
        self.client.force_login(self.director_ajeno)
        respuesta = self.client.get(self.url_lista)
        self.assertContains(respuesta, 'Estudiante De Otro')
        self.assertNotContains(respuesta, 'Estudiante Mio')

    def test_modales_ubicados_fuera_de_main_vi_body(self):
        informe = self.crear_informe('modales_test', nombre='Estudiante Modal')
        self.entrar_como_director()
        respuesta = self.client.get(self.url_lista)
        self.assertEqual(respuesta.status_code, 200)

        contenido = respuesta.content.decode('utf-8')
        pos_main_close = contenido.find('</main>')
        pos_modal_apr = contenido.find(f'id="modal-apr-{informe.pk}"')
        pos_modal_rec = contenido.find(f'id="modal-rec-{informe.pk}"')

        self.assertNotEqual(pos_main_close, -1)
        self.assertNotEqual(pos_modal_apr, -1)
        self.assertNotEqual(pos_modal_rec, -1)
        # Los modales deben ubicarse después del cierre de </main>
        self.assertGreater(pos_modal_apr, pos_main_close)
        self.assertGreater(pos_modal_rec, pos_main_close)
        # Ambos botones de confirmación deben estar presentes y funcionales
        self.assertContains(respuesta, 'Confirmar Aprobado en UP')
        self.assertContains(respuesta, 'Confirmar Rechazado en UP')
