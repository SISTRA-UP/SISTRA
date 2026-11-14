"""SISTRA-04 · Notificación de cargue UP: pruebas.

Solo el responsable de este requisito edita este archivo.
Se ejecutan con: uv run python manage.py test
"""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.forms.aviso_propuesta import (
    ACCION_AUDITORIA_AVISO,
    MSG_04_02,
    MSG_04_03,
    MSG_04_04,
    MSG_04_05,
    MSG_04_06,
    TIPO_NOTIFICACION_AVISO,
)
from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.cargue_up.views.aviso_propuesta import confirmacion, registrar
from apps.parametrizacion.models import (
    Carrera,
    EstadoPeriodo,
    Facultad,
    PeriodoAcademico,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()


class ValidacionAvisoPropuestaTestCase(TestCase):
    """Cubre acceso, permiso, propiedad y estado previo al aviso de cargue."""

    def setUp(self):
        self.factory = RequestFactory()
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self.rol_director = Rol.objects.get(nombre='Director')

        self.facultad = Facultad.objects.create(
            nombre='Facultad de Ingenierías y Arquitectura',
            estado=Estado.ACTIVO,
        )
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería de Sistemas',
            codigo='IS-001',
            estado=Estado.ACTIVO,
        )
        hoy = timezone.localdate()
        self.periodo = PeriodoAcademico.objects.create(
            nombre='2026-2',
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin=hoy + timedelta(days=120),
            fecha_cierre_propuesta=hoy + timedelta(days=60),
            fecha_cierre_informe=hoy + timedelta(days=90),
            estado=EstadoPeriodo.VIGENTE,
        )

        self.usuario_estudiante = self._crear_usuario(
            '1098111001', 'Estudiante Uno', self.rol_estudiante
        )
        self.estudiante = self._crear_estudiante(self.usuario_estudiante, 'SIS-001')
        self.propuesta = self._crear_propuesta(
            self.estudiante, 'SIS-001', EstadoTramite.APROBADO
        )

        self.usuario_ajeno = self._crear_usuario(
            '1098111002', 'Estudiante Dos', self.rol_estudiante
        )
        self.estudiante_ajeno = self._crear_estudiante(self.usuario_ajeno, 'SIS-002')
        self.propuesta_ajena = self._crear_propuesta(
            self.estudiante_ajeno, 'SIS-002', EstadoTramite.APROBADO
        )

        self.usuario_director = self._crear_usuario(
            '1098000002', 'Director Activo', self.rol_director
        )
        self.director = Director.objects.create(usuario=self.usuario_director)
        self.asignacion_director = DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=hoy - timedelta(days=60),
            activo=True,
        )

        self.usuario_sin_permiso = self._crear_usuario(
            '1098000001', 'Director Sin Permiso', self.rol_director
        )

    def _crear_usuario(self, cedula: str, nombre: str, rol: Rol):
        correo = f'{cedula}@unipamplona.edu.co'
        return Usuario.objects.create_user(
            correo_institucional=correo,
            password='Password123!',
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=cedula,
            rol=rol,
            requiere_cambio_contrasena=False,
        )

    def _crear_estudiante(self, usuario, codigo: str) -> Estudiante:
        estudiante = Estudiante.objects.create(usuario=usuario)
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=self.carrera,
            fecha_registro=timezone.localdate(),
            estado=EstadoInscripcion.ACTIVO,
        )
        ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.EN_CURSO,
        )
        return estudiante

    def _crear_propuesta(
        self, estudiante: Estudiante, codigo: str, estado: str
    ) -> Propuesta:
        return Propuesta.objects.create(
            proceso=estudiante.inscripciones.get().proceso,
            periodo_academico=self.periodo,
            codigo=codigo,
            titulo=f'Propuesta {codigo}',
            estado=estado,
        )

    def _peticion(self, usuario):
        request = self.factory.get(f'/cargue-up/avisar/{self.propuesta.pk}/')
        request.user = usuario
        return request

    def _peticion_post(self, usuario, propuesta=None):
        propuesta = propuesta or self.propuesta
        request = self.factory.post(
            f'/cargue-up/avisar/{propuesta.pk}/confirmar/'
        )
        request.user = usuario
        return request

    def _confirmar(self):
        request = self._peticion_post(self.usuario_estudiante)
        return registrar(request, self.propuesta.pk)

    def _assert_sin_registros_de_aviso(self):
        self.assertFalse(CargueUp.objects.filter(propuesta=self.propuesta).exists())
        self.assertFalse(HistorialEstado.objects.filter(propuesta=self.propuesta).exists())
        self.assertFalse(Notificacion.objects.filter(propuesta=self.propuesta).exists())
        self.assertFalse(
            Auditoria.objects.filter(accion=ACCION_AUDITORIA_AVISO).exists()
        )

    def test_usuario_anonimo_redirige_al_login(self):
        request = self._peticion(AnonymousUser())

        response = confirmacion(request, self.propuesta.pk)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('usuarios:login')))

    def test_usuario_sin_permiso_es_rechazado(self):
        request = self._peticion(self.usuario_sin_permiso)

        with self.assertRaises(PermissionDenied):
            confirmacion(request, self.propuesta.pk)

    def test_propuesta_ajena_responde_404(self):
        request = self._peticion(self.usuario_estudiante)

        with self.assertRaises(Http404):
            confirmacion(request, self.propuesta_ajena.pk)

    def test_propuesta_no_aprobada_muestra_boton_deshabilitado(self):
        estados_no_aprobados = [
            EstadoTramite.BORRADOR,
            EstadoTramite.EN_REVISION,
            EstadoTramite.REQUIERE_MODIFICACION,
            EstadoTramite.RECHAZADO,
            EstadoTramite.APROBADO_EN_UP,
        ]

        for estado in estados_no_aprobados:
            with self.subTest(estado=estado):
                self.propuesta.estado = estado
                self.propuesta.save(update_fields=['estado'])
                request = self._peticion(self.usuario_estudiante)

                response = confirmacion(request, self.propuesta.pk)
                contenido = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.propuesta.codigo)
                self.assertContains(response, estado)
                self.assertContains(response, MSG_04_02)
                self.assertContains(
                    response,
                    'El aviso solo está disponible cuando la propuesta se encuentra en',
                )
                self.assertNotContains(response, MSG_04_06)
                atributos_boton = contenido.split(
                    'id="btn-abrir-aviso"', 1
                )[1].split('>', 1)[0]
                self.assertIn('disabled', atributos_boton)
                self._assert_sin_registros_de_aviso()
                self.propuesta.refresh_from_db()
                self.assertEqual(self.propuesta.estado, estado)

    def test_propuesta_subida_en_up_muestra_mensaje_especifico(self):
        self.propuesta.estado = EstadoTramite.SUBIDO_EN_UP
        self.propuesta.save(update_fields=['estado'])
        request = self._peticion(self.usuario_estudiante)

        response = confirmacion(request, self.propuesta.pk)
        contenido = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, EstadoTramite.SUBIDO_EN_UP)
        self.assertContains(response, MSG_04_06)
        self.assertNotContains(response, MSG_04_02)
        self.assertNotContains(
            response,
            'El aviso solo está disponible cuando la propuesta se encuentra en',
        )
        atributos_boton = contenido.split(
            'id="btn-abrir-aviso"', 1
        )[1].split('>', 1)[0]
        self.assertIn('disabled', atributos_boton)
        self._assert_sin_registros_de_aviso()
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_propuesta_aprobada_habilita_el_aviso(self):
        request = self._peticion(self.usuario_estudiante)

        response = confirmacion(request, self.propuesta.pk)
        contenido = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.propuesta.codigo)
        self.assertContains(response, EstadoTramite.APROBADO)
        self.assertContains(
            response,
            'La propuesta está aprobada y lista para avisar su cargue en UP.',
        )
        atributos_boton = contenido.split(
            'id="btn-abrir-aviso"', 1
        )[1].split('>', 1)[0]
        self.assertNotIn('disabled', atributos_boton)
        self.assertIn('data-bs-target="#modal-confirmar-aviso"', atributos_boton)
        self._assert_sin_registros_de_aviso()
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.APROBADO)

    def test_interfaz_muestra_modal_y_cancelar_no_envia_post(self):
        self.client.force_login(self.usuario_estudiante)
        url_confirmacion = reverse(
            'cargue_up:aviso_propuesta_confirmacion',
            kwargs={'id_propuesta': self.propuesta.pk},
        )
        url_registrar = reverse(
            'cargue_up:aviso_propuesta_registrar',
            kwargs={'id_propuesta': self.propuesta.pk},
        )

        response = self.client.get(url_confirmacion)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, 'cargue_up/aviso_propuesta/confirmar.html'
        )
        self.assertContains(response, 'id="modal-confirmar-aviso"')
        self.assertContains(response, f'action="{url_registrar}"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(
            response,
            'type="button" class="btn-secundario" data-bs-dismiss="modal"',
        )
        self._assert_sin_registros_de_aviso()
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.APROBADO)

    def test_post_anonimo_redirige_al_login(self):
        request = self._peticion_post(AnonymousUser())

        response = registrar(request, self.propuesta.pk)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('usuarios:login')))
        self._assert_sin_registros_de_aviso()

    def test_post_sin_permiso_es_rechazado(self):
        request = self._peticion_post(self.usuario_sin_permiso)

        with self.assertRaises(PermissionDenied):
            registrar(request, self.propuesta.pk)

        self._assert_sin_registros_de_aviso()

    def test_post_propuesta_ajena_responde_404(self):
        request = self._peticion_post(
            self.usuario_estudiante, self.propuesta_ajena
        )

        with self.assertRaises(Http404):
            registrar(request, self.propuesta_ajena.pk)

        self.assertFalse(
            CargueUp.objects.filter(propuesta=self.propuesta_ajena).exists()
        )

    def test_post_propuesta_no_aprobada_no_registra_nada(self):
        estados_no_aprobados = [
            EstadoTramite.BORRADOR,
            EstadoTramite.EN_REVISION,
            EstadoTramite.REQUIERE_MODIFICACION,
            EstadoTramite.RECHAZADO,
            EstadoTramite.APROBADO_EN_UP,
        ]

        for estado in estados_no_aprobados:
            with self.subTest(estado=estado):
                self.propuesta.estado = estado
                self.propuesta.save(update_fields=['estado'])
                request = self._peticion_post(self.usuario_estudiante)

                response = registrar(request, self.propuesta.pk)
                cuerpo = json.loads(response.content)

                self.assertEqual(response.status_code, 409)
                self.assertFalse(cuerpo['ok'])
                self._assert_sin_registros_de_aviso()
                self.propuesta.refresh_from_db()
                self.assertEqual(self.propuesta.estado, estado)

    def test_post_registra_cargue_estado_historial_aviso_y_auditoria(self):
        response = self._confirmar()
        cuerpo = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(cuerpo['ok'])
        self.assertTrue(cuerpo['creado'])
        self.assertFalse(cuerpo['duplicado'])

        cargue = CargueUp.objects.get(propuesta=self.propuesta)
        self.assertEqual(cargue.estado_verificacion, EstadoVerificacion.PENDIENTE)
        self.assertIsNotNone(cargue.fecha_declaracion)

        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.SUBIDO_EN_UP)

        historial = HistorialEstado.objects.get(propuesta=self.propuesta)
        self.assertEqual(historial.usuario, self.usuario_estudiante)
        self.assertEqual(historial.estado_anterior, EstadoTramite.APROBADO)
        self.assertEqual(historial.estado_nuevo, EstadoTramite.SUBIDO_EN_UP)
        self.assertEqual(historial.tipo_accion, ACCION_AUDITORIA_AVISO)

        notificacion = Notificacion.objects.get(propuesta=self.propuesta)
        self.assertEqual(notificacion.usuario, self.usuario_director)
        self.assertEqual(notificacion.tipo, TIPO_NOTIFICACION_AVISO)
        self.assertIn(self.propuesta.codigo, notificacion.mensaje)
        self.assertIsNone(notificacion.fecha_lectura)

        auditoria = Auditoria.objects.get(accion=ACCION_AUDITORIA_AVISO)
        self.assertEqual(auditoria.usuario, self.usuario_estudiante)
        self.assertEqual(auditoria.tabla_afectada, 'propuesta')
        self.assertEqual(auditoria.id_registro_afectado, self.propuesta.pk)
        self.assertEqual(auditoria.resultado, 'Éxito')
        self.assertIn(str(cargue.pk), auditoria.detalle)

    def test_post_repetido_no_duplica_cargue_ni_aviso(self):
        self._confirmar()
        totales = {
            'cargues': CargueUp.objects.filter(propuesta=self.propuesta).count(),
            'historial': HistorialEstado.objects.filter(propuesta=self.propuesta).count(),
            'notificaciones': Notificacion.objects.filter(propuesta=self.propuesta).count(),
            'auditorias': Auditoria.objects.filter(
                accion=ACCION_AUDITORIA_AVISO
            ).count(),
        }

        response = self._confirmar()
        cuerpo = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(cuerpo['ok'])
        self.assertFalse(cuerpo['creado'])
        self.assertTrue(cuerpo['duplicado'])
        self.assertEqual(cuerpo['mensaje'], MSG_04_03)
        self.assertEqual(
            CargueUp.objects.filter(propuesta=self.propuesta).count(),
            totales['cargues'],
        )
        self.assertEqual(
            HistorialEstado.objects.filter(propuesta=self.propuesta).count(),
            totales['historial'],
        )
        self.assertEqual(
            Notificacion.objects.filter(propuesta=self.propuesta).count(),
            totales['notificaciones'],
        )
        self.assertEqual(
            Auditoria.objects.filter(accion=ACCION_AUDITORIA_AVISO).count(),
            totales['auditorias'],
        )
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.SUBIDO_EN_UP)

    def test_post_permite_nuevo_intento_tras_rechazo_en_up(self):
        self.propuesta.estado = EstadoTramite.SUBIDO_EN_UP
        self.propuesta.save(update_fields=['estado'])
        cargue_rechazado = CargueUp.objects.create(
            propuesta=self.propuesta,
            estado_verificacion=EstadoVerificacion.RECHAZADO_EN_UP,
            fecha_declaracion=timezone.now() - timedelta(days=1),
            fecha_verificacion=timezone.now() - timedelta(hours=12),
            observacion='El documento cargado no corresponde a la propuesta.',
        )
        self.propuesta.estado = EstadoTramite.APROBADO
        self.propuesta.save(update_fields=['estado'])

        response = self._confirmar()
        cuerpo = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(cuerpo['creado'])
        self.assertEqual(
            CargueUp.objects.filter(propuesta=self.propuesta).count(), 2
        )
        cargue_nuevo = CargueUp.objects.get(
            propuesta=self.propuesta,
            estado_verificacion=EstadoVerificacion.PENDIENTE,
        )
        self.assertNotEqual(cargue_nuevo.pk, cargue_rechazado.pk)
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.SUBIDO_EN_UP)
        self.assertEqual(
            Notificacion.objects.filter(propuesta=self.propuesta).count(), 1
        )
        self.assertEqual(
            HistorialEstado.objects.filter(propuesta=self.propuesta).count(), 1
        )

    def test_post_sin_director_activo_no_registra_nada(self):
        self.asignacion_director.activo = False
        self.asignacion_director.save(update_fields=['activo'])

        response = self._confirmar()
        cuerpo = json.loads(response.content)

        self.assertEqual(response.status_code, 409)
        self.assertFalse(cuerpo['ok'])
        self.assertEqual(cuerpo['mensaje'], MSG_04_04)
        self._assert_sin_registros_de_aviso()
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.APROBADO)

    def test_post_revierte_todo_si_falla_la_notificacion(self):
        with patch(
            'apps.cargue_up.views.aviso_propuesta.Notificacion.objects.create',
            side_effect=RuntimeError('Fallo simulado al notificar'),
        ):
            response = self._confirmar()

        cuerpo = json.loads(response.content)

        self.assertEqual(response.status_code, 500)
        self.assertFalse(cuerpo['ok'])
        self.assertEqual(cuerpo['mensaje'], MSG_04_05)
        self._assert_sin_registros_de_aviso()
        self.propuesta.refresh_from_db()
        self.assertEqual(self.propuesta.estado, EstadoTramite.APROBADO)
