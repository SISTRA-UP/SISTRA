"""SISTRA-01 · Prueba de concurrencia al enviar una propuesta."""

import threading
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from apps.parametrizacion.models import Carrera, EstadoPeriodo, Facultad, PeriodoAcademico
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.propuestas.tests.test_montaje import DATOS_COMPLETOS_ENVIO
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()


class ConcurrencySendTest(TransactionTestCase):
    """Verifica que dos envíos concurrentes no dupliquen historial ni notificaciones."""

    serialized_rollback = True

    def setUp(self):
        hoy = timezone.localdate()
        self.rol_estudiante, _ = Rol.objects.get_or_create(nombre='Estudiante')
        self.rol_director, _ = Rol.objects.get_or_create(nombre='Director')

        facultad = Facultad.objects.create(
            nombre='Facultad Concurrencia', estado=Estado.ACTIVO
        )
        carrera = Carrera.objects.create(
            facultad=facultad,
            nombre='Trabajo Social Concurrencia',
            codigo='TS-CONC',
            estado=Estado.ACTIVO,
        )
        self.periodo = PeriodoAcademico.objects.create(
            nombre='2026-2',
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin=hoy + timedelta(days=120),
            fecha_cierre_propuesta=hoy + timedelta(days=40),
            fecha_cierre_informe=hoy + timedelta(days=100),
            estado=EstadoPeriodo.VIGENTE,
        )

        user_director = Usuario.objects.create_user(
            correo_institucional='director.conc@unipamplona.edu.co',
            password='Password123!',
            nombre='Director Concurrencia',
            cedula='1098777001',
            nombre_usuario='director.conc',
            rol=self.rol_director,
            requiere_cambio_contrasena=False,
        )
        director = Director.objects.create(usuario=user_director)
        DirectorCarrera.objects.create(
            director=director,
            carrera=carrera,
            fecha_inicio=hoy - timedelta(days=60),
            activo=True,
        )

        self.user = Usuario.objects.create_user(
            correo_institucional='estudiante.conc@unipamplona.edu.co',
            password='Password123!',
            nombre='Estudiante Concurrencia',
            cedula='1098777002',
            nombre_usuario='estudiante.conc',
            rol=self.rol_estudiante,
            requiere_cambio_contrasena=False,
        )
        estudiante = Estudiante.objects.create(usuario=self.user)
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=carrera,
            fecha_registro=hoy - timedelta(days=20),
            estado=EstadoInscripcion.ACTIVO,
        )
        self.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now() - timedelta(days=15),
            estado=EstadoAvance.EN_CURSO,
        )

        # Propuesta existente en Borrador lista para enviar
        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo=f'PROP-CONC-{self.proceso.pk}',
            estado=EstadoTramite.BORRADOR,
            titulo=DATOS_COMPLETOS_ENVIO['titulo'],
            entidad=DATOS_COMPLETOS_ENVIO['entidad'],
            sector_entidad=DATOS_COMPLETOS_ENVIO['sector_entidad'],
            sector=DATOS_COMPLETOS_ENVIO['sector'],
            zona=DATOS_COMPLETOS_ENVIO['zona'],
            area=DATOS_COMPLETOS_ENVIO['area'],
            unidad=DATOS_COMPLETOS_ENVIO['unidad'],
            poblacion_beneficiada=DATOS_COMPLETOS_ENVIO['poblacion_beneficiada'],
            identificacion_poblacion=DATOS_COMPLETOS_ENVIO['identificacion_poblacion'],
            resena_historica=DATOS_COMPLETOS_ENVIO['resena_historica'],
            identificacion_necesidad=DATOS_COMPLETOS_ENVIO['identificacion_necesidad'],
            justificacion=DATOS_COMPLETOS_ENVIO['justificacion'],
            objetivos=DATOS_COMPLETOS_ENVIO['objetivos'],
            referente_teorico=DATOS_COMPLETOS_ENVIO['referente_teorico'],
            propuesta_social=DATOS_COMPLETOS_ENVIO['propuesta_social'],
            impacto_social=DATOS_COMPLETOS_ENVIO['impacto_social'],
            fecha_inicio=hoy,
            fecha_fin=hoy + timedelta(days=90),
        )

    def test_concurrent_send(self):
        hoy = timezone.localdate()
        payload = {
            **DATOS_COMPLETOS_ENVIO,
            'fecha_inicio': str(hoy),
            'fecha_fin': str(hoy + timedelta(days=90)),
        }
        url = reverse('propuestas:montaje')
        barrier = threading.Barrier(2)

        def send():
            try:
                client = Client()
                client.force_login(self.user)
                barrier.wait(timeout=5)
                client.post(url, payload)
            finally:
                connections.close_all()

        thread1 = threading.Thread(target=send)
        thread2 = threading.Thread(target=send)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        self.assertEqual(
            Propuesta.objects.filter(
                proceso=self.proceso, estado=EstadoTramite.EN_REVISION
            ).count(),
            1,
        )
        self.assertEqual(
            HistorialEstado.objects.filter(propuesta=self.propuesta).count(),
            1,
        )
        self.assertEqual(
            Notificacion.objects.filter(propuesta=self.propuesta).count(),
            1,
        )
        self.assertEqual(
            Auditoria.objects.filter(
                tabla_afectada='propuesta',
                id_registro_afectado=self.propuesta.pk,
                resultado='Bloqueado',
            ).count(),
            1,
        )
