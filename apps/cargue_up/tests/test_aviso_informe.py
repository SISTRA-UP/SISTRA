"""SISTRA-08 · Notificación de cargue UP (informe): pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

from django.test import TestCase  # noqa: F401
from datetime import date, timedelta
from unittest import mock

from io import StringIO

from django.core import mail
from django.core.management import call_command

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.models import CargueUp
from apps.informes.models import Informe
from apps.parametrizacion.models import Carrera, Facultad, PeriodoAcademico
from apps.parametrizacion.servicios import guardar
from apps.personas.models import (
    Director, DirectorCarrera, Estudiante, EstudianteCarrera,
)
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.models import Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Permiso, Rol, RolPermiso
from apps.cargue_up.models import CargueUp, EstadoVerificacion

from django.contrib import messages
from django.contrib.messages import get_messages


Usuario = get_user_model()

# ---------------------------------------------------------------- AJUSTES
URL_INICIO = 'cargue_up:aviso_informe'
URL_CONFIRMAR = 'cargue_up:aviso_informe_confirmar'
PERMISO = 'cargue_up.avisar'
CLAVE = 'ClaveDePrueba123'
ESTADO_APROBADO = 'Aprobado'
ESTADO_SUBIDO = 'Subido en UP'
ACCION_OK = 'AVISAR_SUBIDO_UP_INFORME'
ACCION_BLOQUEADO = 'AVISAR_SUBIDO_UP_INFORME_BLOQUEADO'
URL_IR_UP = 'cargue_up:aviso_informe_ir_up'
URL_DESCARGAR = 'cargue_up:aviso_informe_descargar'
ACCION_IR_UP = 'Ir a la Plataforma UP (informe)'
ACCION_DESCARGAR = 'Descargar informe'
URL_UP = 'https://up.ejemplo.edu.co/'
RUTA_URL_UP = 'apps.cargue_up.views.aviso_informe._url_up'
TIPO_RECORDATORIO = 'RECORDATORIO_CARGUE_UP_INFORME'
URL_PANTALLA = 'cargue_up:cargue_propuesta'
URL_DESCARGAR = 'cargue_up:aviso_informe_descargar'
RUTA_PDF = 'apps.cargue_up.views.aviso_informe.generar_pdf_informe'


def _post_confirmar(client, informe_id):
    return client.post(reverse(URL_CONFIRMAR), {'id_informe': informe_id})


def _mensajes(respuesta):
    """Lista de (nivel, texto) de los mensajes que dejó la vista."""
    return [(m.level, m.message) for m in get_messages(respuesta.wsgi_request)]

# ---------------------------------------------------------------- helpers
def _crear_usuario(rol, n, **extra):
    return Usuario.objects.create_user(
        correo_institucional=f'u{n}@ejemplo.edu.co',
        password=CLAVE,
        nombre=f'Usuario {n}',
        cedula=f'100000{n}',
        nombre_usuario=f'u{n}',
        rol=rol,
        requiere_cambio_contrasena=extra.pop('requiere_cambio_contrasena', False),
        **extra,
    )


def _crear_informe(carrera, periodo, estudiante, estado=ESTADO_APROBADO, n=1):
    ec = EstudianteCarrera.objects.create(
        estudiante=estudiante, carrera=carrera, estado='Activo')
    proceso = ProcesoTrabajoSocial.objects.create(
        estudiante_carrera=ec, fecha_inicio=timezone.now(), estado='En curso')
    texto = 'texto de prueba'
    propuesta = Propuesta.objects.create(
        proceso=proceso, periodo_academico=periodo, codigo=f'PRO-{n}',
        titulo=f'Propuesta {n}', resena_historica=texto,
        identificacion_necesidad=texto, justificacion=texto, objetivos=texto,
        referente_teorico=texto, impacto_social=texto,
        identificacion_poblacion=texto, propuesta_social=texto,
        entidad='Entidad', sector_entidad='Público', poblacion_beneficiada=texto,
        zona=texto, area=texto, sector=texto, unidad=texto,
        fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 6, 1),
        estado='Aprobado en UP', fecha_creacion=timezone.now(),
        fecha_actualizacion=timezone.now(),
    )
    return Informe.objects.create(
        propuesta=propuesta, periodo_academico=periodo, codigo=f'INF-{n}',
        resultados=texto, conclusiones=texto, recomendaciones=texto,
        estado=estado, version_entrega=1,
        fecha_creacion=timezone.now(), fecha_actualizacion=timezone.now(),
    )

class AvisoInformeBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.rol_est, _ = Rol.objects.get_or_create(nombre='Estudiante')
        cls.rol_dir, _ = Rol.objects.get_or_create(nombre='Director')
        permiso, _ = Permiso.objects.get_or_create(nombre=PERMISO)
        RolPermiso.objects.get_or_create(rol=cls.rol_est, permiso=permiso)

        facultad = Facultad.objects.create(nombre='Derecho')
        cls.carrera = Carrera.objects.create(
            facultad=facultad, nombre='Derecho', codigo='DER')
        cls.periodo = PeriodoAcademico.objects.create(
            nombre='2026-1', fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31), fecha_cierre_propuesta=date(2026, 4, 1),
            fecha_cierre_informe=date(2026, 11, 1), estado='Vigente')

        cls.user_dir = _crear_usuario(cls.rol_dir, 1)
        director = Director.objects.create(usuario=cls.user_dir)
        DirectorCarrera.objects.create(
            director=director, carrera=cls.carrera,
            fecha_inicio=date(2026, 1, 1), activo=True)

        cls.user_est = _crear_usuario(cls.rol_est, 2)
        cls.user_otro = _crear_usuario(cls.rol_est, 3)
        est = Estudiante.objects.create(usuario=cls.user_est)
        otro = Estudiante.objects.create(usuario=cls.user_otro)
        cls.informe = _crear_informe(cls.carrera, cls.periodo, est, n=1)
        cls.informe_otro = _crear_informe(cls.carrera, cls.periodo, otro, n=2)

    def entrar(self, usuario):
        self.client.force_login(usuario)


class PantallaTests(AvisoInformeBase):
    AVISO_BLOQUEO = 'Esta sección se habilita cuando tu Director apruebe el informe.'

    def _get(self):
        self.entrar(self.user_est)
        return self.client.get(reverse(URL_PANTALLA))

    def test_aprobado_muestra_las_acciones(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="panel-informe"')
        self.assertContains(r, reverse(URL_DESCARGAR))
        self.assertContains(r, f'action="{reverse(URL_CONFIRMAR)}"')
        self.assertContains(r, 'data-bs-target="#modal-confirmar-informe"')  # texto del botón
        self.assertNotContains(r, self.AVISO_BLOQUEO)

    def test_en_revision_bloquea(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado='En revisión')
        r = self._get()
        self.assertContains(r, self.AVISO_BLOQUEO)
        self.assertNotContains(r, f'action="{reverse(URL_CONFIRMAR)}"')
        self.assertNotContains(r, reverse(URL_DESCARGAR))

    def test_sin_informe(self):
        Informe.objects.filter(pk=self.informe.pk).delete()
        r = self._get()
        self.assertContains(r, 'Sin informe')
        self.assertContains(r, self.AVISO_BLOQUEO)

    def test_con_url_up_muestra_el_enlace(self):
        with mock.patch(RUTA_URL_UP, return_value=URL_UP):
            r = self._get()
        self.assertContains(r, reverse(URL_IR_UP))
        self.assertContains(r, 'target="_blank"')

    def test_sin_url_up_no_hay_enlace(self):
        with mock.patch(RUTA_URL_UP, return_value=None):
            r = self._get()
        self.assertNotContains(r, reverse(URL_IR_UP))
        self.assertContains(
            r, 'El enlace a la Plataforma UP no está disponible por ahora.')

    def test_subido_en_up(self):
        CargueUp.objects.create(
            informe=self.informe, fecha_declaracion=timezone.now(),
            estado_verificacion=EstadoVerificacion.PENDIENTE)
        Informe.objects.filter(pk=self.informe.pk).update(estado=ESTADO_SUBIDO)
        r = self._get()
        self.assertContains(r, 'Ya avisaste a tu director que subiste el informe')
        self.assertNotContains(r, f'action="{reverse(URL_CONFIRMAR)}"')

    def test_aprobado_en_up(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado='Aprobado en UP')
        r = self._get()
        self.assertContains(r, 'Tu director verificó el informe en la Plataforma UP.')
        self.assertNotContains(r, 'Lo verificará')

    def test_el_form_lleva_solo_el_id_propio(self):
        r = self._get()
        self.assertContains(r, f'name="id_informe" value="{self.informe.pk}"')
        self.assertNotContains(
            r, f'name="id_informe" value="{self.informe_otro.pk}"')

    def test_la_direccion_vieja_redirige_a_la_pantalla(self):
        self.entrar(self.user_est)
        r = self.client.get(reverse(URL_INICIO))
        self.assertRedirects(r, reverse(URL_PANTALLA), fetch_redirect_response=False)


class ConfirmarTests(AvisoInformeBase):
    def _sin_efectos(self, informe):
        self.assertFalse(CargueUp.objects.filter(informe=informe).exists())
        self.assertFalse(Notificacion.objects.filter(informe=informe).exists())
        informe.refresh_from_db()
        self.assertNotEqual(informe.estado, ESTADO_SUBIDO)

    def test_ca03_confirmar_registra_todo(self):
        self.entrar(self.user_est)
        r = _post_confirmar(self.client, self.informe.pk)
        self.assertRedirects(r, reverse(URL_PANTALLA), fetch_redirect_response=False)
        self.assertEqual(_mensajes(r)[0][0], messages.SUCCESS)

        self.informe.refresh_from_db()
        self.assertEqual(self.informe.estado, ESTADO_SUBIDO)

        cargue = CargueUp.objects.get(informe=self.informe)
        self.assertEqual(cargue.estado_verificacion, 'Pendiente')
        self.assertIsNone(cargue.director)

        self.assertTrue(HistorialEstado.objects.filter(
            informe=self.informe, estado_nuevo=ESTADO_SUBIDO,
            usuario=self.user_est).exists())
        self.assertEqual(Notificacion.objects.filter(
            usuario=self.user_dir, informe=self.informe,
            tipo=ESTADO_SUBIDO).count(), 1)
        self.assertTrue(Auditoria.objects.filter(
            usuario=self.user_est, accion=ACCION_OK, resultado='Éxito').exists())

    def test_ca04_duplicado_no_crea_nada_nuevo(self):
        self.entrar(self.user_est)
        _post_confirmar(self.client, self.informe.pk)
        r = _post_confirmar(self.client, self.informe.pk)

        self.assertEqual(r.status_code, 302)
        self.assertEqual(_mensajes(r)[-1][0], messages.INFO)
        self.assertEqual(CargueUp.objects.filter(informe=self.informe).count(), 1)
        self.assertEqual(Notificacion.objects.filter(informe=self.informe).count(), 1)
        self.assertTrue(Auditoria.objects.filter(
            accion=ACCION_BLOQUEADO, resultado='Bloqueado').exists())

    def test_informe_no_aprobado_es_rechazado(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado='En revisión')
        self.entrar(self.user_est)
        r = _post_confirmar(self.client, self.informe.pk)

        self.assertEqual(r.status_code, 302)
        self.assertEqual(_mensajes(r)[0][0], messages.WARNING)
        self._sin_efectos(self.informe)
        self.assertTrue(Auditoria.objects.filter(
            accion=ACCION_BLOQUEADO, resultado='Bloqueado').exists())

    def test_ca05_estudiante_ajeno_no_puede(self):
        self.entrar(self.user_otro)
        antes = Auditoria.objects.count()
        r = _post_confirmar(self.client, self.informe.pk)

        self.assertEqual(r.status_code, 302)
        self.assertNotEqual(_mensajes(r)[0][0], messages.SUCCESS)
        self._sin_efectos(self.informe)
        self.assertEqual(Auditoria.objects.count(), antes + 1)

    def test_director_recibe_403(self):
        self.entrar(self.user_dir)
        r = _post_confirmar(self.client, self.informe.pk)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(CargueUp.objects.exists())

    def test_sin_permiso_recibe_403(self):
        RolPermiso.objects.filter(rol=self.rol_est, permiso__nombre=PERMISO).delete()
        self.entrar(self.user_est)
        r = _post_confirmar(self.client, self.informe.pk)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(CargueUp.objects.exists())

    def test_sin_sesion_redirige_al_login(self):
        r = _post_confirmar(self.client, self.informe.pk)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/login/', r.url)
        self.assertFalse(CargueUp.objects.exists())

    def test_primer_ingreso_redirige_a_cambiar_contrasena(self):
        Usuario.objects.filter(pk=self.user_est.pk).update(
            requiere_cambio_contrasena=True)
        self.client.force_login(Usuario.objects.get(pk=self.user_est.pk))
        r = _post_confirmar(self.client, self.informe.pk)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/usuarios/cambiar-contrasena/', r.url)
        self.assertFalse(CargueUp.objects.exists())

    def test_id_invalido(self):
        self.entrar(self.user_est)
        for valor in ('abc', '999999', ''):
            r = _post_confirmar(self.client, valor)
            self.assertEqual(r.status_code, 302, valor)
            self.assertNotEqual(_mensajes(r)[0][0], messages.SUCCESS, valor)
        self.assertFalse(CargueUp.objects.exists())

    def test_get_no_confirma(self):
        self.entrar(self.user_est)
        r = self.client.get(reverse(URL_CONFIRMAR))
        self.assertEqual(r.status_code, 405)
        self.assertFalse(CargueUp.objects.exists())

class AtomicidadTests(AvisoInformeBase):
    def test_si_falla_el_aviso_se_deshace_todo(self):
        self.client.raise_request_exception = False
        self.entrar(self.user_est)
        with mock.patch.object(
                Notificacion, 'save', side_effect=RuntimeError('fallo simulado')):
            r = _post_confirmar(self.client, self.informe.pk)
        self.assertGreaterEqual(r.status_code, 300)

        self.informe.refresh_from_db()
        self.assertEqual(self.informe.estado, ESTADO_APROBADO)
        self.assertFalse(CargueUp.objects.filter(informe=self.informe).exists())
        self.assertFalse(HistorialEstado.objects.filter(
            informe=self.informe, estado_nuevo=ESTADO_SUBIDO).exists())

class IrAUpTests(AvisoInformeBase):
    def test_aprobado_redirige_a_la_url_y_audita_exito(self):
        self.entrar(self.user_est)
        with mock.patch(RUTA_URL_UP, return_value=URL_UP):
            r = self.client.get(reverse(URL_IR_UP))
        self.assertRedirects(r, URL_UP, fetch_redirect_response=False)
        self.assertTrue(Auditoria.objects.filter(
            usuario=self.user_est, accion=ACCION_IR_UP, resultado='Éxito',
            id_registro_afectado=self.informe.pk).exists())

    def test_no_aprobado_no_redirige_y_audita_bloqueado(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado='En revisión')
        self.entrar(self.user_est)
        with mock.patch(RUTA_URL_UP, return_value=URL_UP):
            r = self.client.get(reverse(URL_IR_UP))
        self.assertRedirects(r, reverse(URL_PANTALLA), fetch_redirect_response=False)
        self.assertEqual(_mensajes(r)[0][0], messages.WARNING)
        self.assertTrue(Auditoria.objects.filter(
            accion=ACCION_IR_UP, resultado='Bloqueado').exists())

    def test_sin_url_audita_bloqueado_y_avisa(self):
        self.entrar(self.user_est)
        with mock.patch(RUTA_URL_UP, return_value=None):
            r = self.client.get(reverse(URL_IR_UP))
        self.assertRedirects(r, reverse(URL_PANTALLA), fetch_redirect_response=False)
        self.assertEqual(_mensajes(r)[0][0], messages.ERROR)
        self.assertTrue(Auditoria.objects.filter(
            accion=ACCION_IR_UP, resultado='Bloqueado', detalle='sin_url_up').exists())

    def test_director_recibe_403(self):
        self.entrar(self.user_dir)
        r = self.client.get(reverse(URL_IR_UP))
        self.assertEqual(r.status_code, 403)


class DescargarTests(AvisoInformeBase):
    def test_no_aprobado_es_bloqueado(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado='En revisión')
        self.entrar(self.user_est)
        r = self.client.get(reverse(URL_DESCARGAR))
        self.assertRedirects(r, reverse(URL_PANTALLA), fetch_redirect_response=False)
        self.assertEqual(_mensajes(r)[0][0], messages.WARNING)
        self.assertTrue(Auditoria.objects.filter(
            accion=ACCION_DESCARGAR, resultado='Bloqueado').exists())

    def test_aprobado_audita_fallo_con_msg_08_04(self):
        self.entrar(self.user_est)
        r = self.client.get(reverse(URL_DESCARGAR))
        self.assertRedirects(r, reverse(URL_PANTALLA), fetch_redirect_response=False)
        nivel, texto = _mensajes(r)[0]
        self.assertEqual(nivel, messages.ERROR)
        self.assertIn('No pudimos completar la acción', texto)
        self.assertTrue(Auditoria.objects.filter(
            accion=ACCION_DESCARGAR, resultado='Fallo').exists())

    def test_director_recibe_403(self):
        self.entrar(self.user_dir)
        self.assertEqual(self.client.get(reverse(URL_DESCARGAR)).status_code, 403)

class RecordatorioTests(AvisoInformeBase):
    def setUp(self):
        # El informe del estudiante 1 se aprobó hace 8 días; el del otro (INF-2), sin historial, es reciente.
        HistorialEstado.objects.create(
            informe=self.informe, usuario=self.user_dir, estado_nuevo='Aprobado',
            tipo_accion='Aprobado', fecha_hora=timezone.now() - timedelta(days=8))

    def _correr(self):
        call_command('recordatorio_cargue_up_informe', '--dias', '7', stdout=StringIO())

    def _recordatorios(self, informe):
        return Notificacion.objects.filter(informe=informe, tipo=TIPO_RECORDATORIO)

    def test_crea_el_recordatorio_sin_correo_y_lo_audita(self):
        self._correr()
        n = self._recordatorios(self.informe)
        self.assertEqual(n.count(), 1)
        notif = n.first()
        self.assertEqual(notif.usuario, self.user_est)
        self.assertIn('aún no has indicado', notif.mensaje)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Auditoria.objects.filter(
            accion='Envío de recordatorio cargue en UP (informe)',
            tabla_afectada='notificacion', id_registro_afectado=notif.pk,
            resultado='Éxito').exists())

    def test_no_repite_antes_de_la_frecuencia(self):
        self._correr()
        self._correr()
        self.assertEqual(self._recordatorios(self.informe).count(), 1)

    def test_repite_pasada_la_frecuencia(self):
        self._correr()
        self._recordatorios(self.informe).update(
            fecha_creacion=timezone.now() - timedelta(days=8))
        self._correr()
        self.assertEqual(self._recordatorios(self.informe).count(), 2)

    def test_se_detiene_con_subido_en_up(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado=ESTADO_SUBIDO)
        self._correr()
        self.assertEqual(self._recordatorios(self.informe).count(), 0)

    def test_no_avisa_informes_archivados_ni_recientes(self):
        Informe.objects.filter(pk=self.informe.pk).update(archivado=True)
        self._correr()
        self.assertEqual(self._recordatorios(self.informe).count(), 0)
        self.assertEqual(self._recordatorios(self.informe_otro).count(), 0)

class DescargarTests(AvisoInformeBase):
    def test_descarga_entrega_pdf_con_nombre_y_auditoria_exito(self):
        self.entrar(self.user_est)
        with mock.patch(RUTA_PDF, return_value=b'%PDF-1.4 prueba'):
            r = self.client.get(reverse(URL_DESCARGAR))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn(f'Informe{self.informe.codigo}.pdf', r['Content-Disposition'])
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertTrue(Auditoria.objects.filter(
            usuario=self.user_est, resultado='Éxito').exists())

    def test_si_falla_la_generacion_queda_fallo_y_msg_08_04(self):
        self.entrar(self.user_est)
        with mock.patch(RUTA_PDF, side_effect=RuntimeError('boom')):
            r = self.client.get(reverse(URL_DESCARGAR))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_mensajes(r)[0][0], messages.ERROR)
        self.assertTrue(Auditoria.objects.filter(
            usuario=self.user_est, resultado='Fallo').exists())

    def test_sin_informe_aprobado_sigue_bloqueada(self):
        Informe.objects.filter(pk=self.informe.pk).update(estado='En revisión')
        self.entrar(self.user_est)
        with mock.patch(RUTA_PDF, return_value=b'%PDF') as generar:
            r = self.client.get(reverse(URL_DESCARGAR))
        self.assertNotEqual(r.get('Content-Type'), 'application/pdf')
        generar.assert_not_called()
        self.assertTrue(Auditoria.objects.filter(resultado='Bloqueado').exists())

    def test_otro_estudiante_no_descarga_el_informe_ajeno(self):
        Informe.objects.filter(pk=self.informe_otro.pk).update(estado='En revisión')
        self.entrar(self.user_otro)
        with mock.patch(RUTA_PDF, return_value=b'%PDF') as generar:
            r = self.client.get(reverse(URL_DESCARGAR))
        self.assertNotEqual(r.get('Content-Type'), 'application/pdf')
        generar.assert_not_called()