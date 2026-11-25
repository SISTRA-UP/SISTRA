"""Pruebas del comando de gestión `alerta_semaforo` (SISTRA-14 / RG-08 · Tarea B5)."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import models
from django.test import TestCase
from django.utils import timezone

from apps.dashboard.management.commands.alerta_semaforo import TIPOS_ALERTA_SEMAFORO
from apps.informes.models import Informe
from apps.parametrizacion.models import (
    Carrera,
    EstadoPeriodo,
    Facultad,
    Parametro,
    PeriodoAcademico,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, RESULTADO_FALLO
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()


class AlertaSemaforoCommandTests(TestCase):
    def setUp(self):
        self.rol_admin = Rol.objects.get(nombre='Administrador')
        self.rol_director = Rol.objects.get(nombre='Director')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')
        self._contador_estudiantes = 0

        Parametro.objects.filter(
            clave__in=['semaforo.verde_hasta_dias', 'semaforo.amarillo_hasta_dias']
        ).delete()

        self.facultad = Facultad.objects.create(nombre='Facultad de Ingenierías')
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería de Sistemas',
            codigo='IS-SEM',
        )
        self.otra_carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería Mecánica',
            codigo='IM-SEM',
        )

        hoy = timezone.localdate()
        self.periodo = PeriodoAcademico.objects.create(
            nombre='2026-2',
            fecha_inicio=hoy - timedelta(days=30),
            fecha_fin=hoy + timedelta(days=90),
            fecha_cierre_propuesta=hoy + timedelta(days=30),
            fecha_cierre_informe=hoy + timedelta(days=60),
            estado=EstadoPeriodo.VIGENTE,
        )

        self.director_user = Usuario.objects.create_user(
            correo_institucional='dir.sistemas@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_director,
            nombre='Director Sistemas',
            cedula='920000001',
            nombre_usuario='dir_sistemas',
            requiere_cambio_contrasena=False,
        )
        self.director = Director.objects.create(usuario=self.director_user)
        self.asignacion_director = DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=hoy,
            activo=True,
        )

        self.otro_director_user = Usuario.objects.create_user(
            correo_institucional='dir.mecanica@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_director,
            nombre='Director Mecánica',
            cedula='920000002',
            nombre_usuario='dir_mecanica',
            requiere_cambio_contrasena=False,
        )
        self.otro_director = Director.objects.create(usuario=self.otro_director_user)
        DirectorCarrera.objects.create(
            director=self.otro_director,
            carrera=self.otra_carrera,
            fecha_inicio=hoy,
            activo=True,
        )

        self.estudiante_user, self.proceso = self._crear_proceso_estudiante()

    def _crear_proceso_estudiante(self, carrera=None):
        self._contador_estudiantes += 1
        idx = self._contador_estudiantes
        usuario = Usuario.objects.create_user(
            correo_institucional=f'est.sem.{idx}@unipamplona.edu.co',
            password='ClaveSegura123!',
            rol=self.rol_estudiante,
            nombre=f'Estudiante Sistemas {idx}',
            cedula=f'9200001{idx:02d}',
            nombre_usuario=f'est_sem_{idx}',
            requiere_cambio_contrasena=False,
        )
        estudiante = Estudiante.objects.create(usuario=usuario)
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=carrera or self.carrera,
            estado=EstadoInscripcion.ACTIVO,
        )
        campo_estado = ProcesoTrabajoSocial._meta.get_field('estado')
        estado_inicial = (
            campo_estado.default
            if campo_estado.default is not models.NOT_PROVIDED
            else campo_estado.choices[0][0]
        )
        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now() - timedelta(days=20),
            estado=estado_inicial,
        )
        return usuario, proceso

    def _crear_propuesta(
        self,
        *,
        dias_en_revision,
        estado=EstadoTramite.EN_REVISION,
        codigo='PROP-SEM-01',
        archivada=False,
        proceso=None,
    ):
        return Propuesta.objects.create(
            proceso=proceso or self.proceso,
            periodo_academico=self.periodo,
            codigo=codigo,
            titulo='Propuesta de prueba semáforo',
            estado=estado,
            fecha_envio=timezone.now() - timedelta(days=dias_en_revision, hours=1),
            archivada=archivada,
        )

    def test_propuesta_8_dias_genera_amarillo_sin_duplicar_y_15_dias_genera_rojo_una_vez(self):
        mail.outbox.clear()
        propuesta = self._crear_propuesta(dias_en_revision=8, codigo='PROP-CICLO-01')

        call_command('alerta_semaforo', stdout=StringIO())

        notifs_amarillas = Notificacion.objects.filter(
            propuesta=propuesta,
            tipo=TIPOS_ALERTA_SEMAFORO['amarillo'],
        )
        self.assertEqual(notifs_amarillas.count(), 1)
        notif_amarilla = notifs_amarillas.first()
        self.assertEqual(notif_amarilla.usuario, self.director_user)
        self.assertEqual(
            notif_amarilla.mensaje,
            'Tienes 1 registros en amarillo esperando tu revisión.',
        )
        self.assertEqual(mail.outbox, [])

        # Correr el comando otra vez en amarillo no crea duplicado
        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(
            Notificacion.objects.filter(propuesta=propuesta).count(),
            1,
        )

        # Al llegar a 15 días sale el aviso rojo una sola vez
        propuesta.fecha_envio = timezone.now() - timedelta(days=15, hours=1)
        propuesta.save(update_fields=['fecha_envio'])

        call_command('alerta_semaforo', stdout=StringIO())
        notifs_rojas = Notificacion.objects.filter(
            propuesta=propuesta,
            tipo=TIPOS_ALERTA_SEMAFORO['rojo'],
        )
        self.assertEqual(notifs_rojas.count(), 1)
        self.assertEqual(
            notifs_rojas.first().mensaje,
            'Tienes 1 registros en rojo esperando tu revisión.',
        )

        # Correrlo de nuevo en rojo no crea otro
        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(
            Notificacion.objects.filter(propuesta=propuesta).count(),
            2,
        )

        # Auditoría sin usuario y con resultado Éxito
        auditorias = Auditoria.objects.filter(
            tabla_afectada='notificacion',
            id_registro_afectado__in=[notif_amarilla.pk, notifs_rojas.first().pk],
        )
        self.assertEqual(auditorias.count(), 2)
        for aud in auditorias:
            self.assertIsNone(aud.usuario)
            self.assertEqual(aud.resultado, RESULTADO_EXITO)

    def test_registro_decidido_y_verde_no_generan_avisos(self):
        _, proc_verde = self._crear_proceso_estudiante()
        _, proc_aprob = self._crear_proceso_estudiante()
        _, proc_mod = self._crear_proceso_estudiante()
        _, proc_rec = self._crear_proceso_estudiante()

        self._crear_propuesta(
            dias_en_revision=3,
            estado=EstadoTramite.EN_REVISION,
            codigo='PROP-VERDE-01',
            proceso=proc_verde,
        )
        self._crear_propuesta(
            dias_en_revision=20,
            estado=EstadoTramite.APROBADO,
            codigo='PROP-APROB-01',
            proceso=proc_aprob,
        )
        self._crear_propuesta(
            dias_en_revision=20,
            estado=EstadoTramite.REQUIERE_MODIFICACION,
            codigo='PROP-MOD-01',
            proceso=proc_mod,
        )
        self._crear_propuesta(
            dias_en_revision=20,
            estado=EstadoTramite.RECHAZADO,
            codigo='PROP-REC-01',
            proceso=proc_rec,
        )

        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_aviso_llega_solo_al_director_de_esa_carrera(self):
        propuesta = self._crear_propuesta(dias_en_revision=9, codigo='PROP-CARRERA-01')

        call_command('alerta_semaforo', stdout=StringIO())

        self.assertEqual(
            Notificacion.objects.filter(
                usuario=self.director_user,
                propuesta=propuesta,
            ).count(),
            1,
        )
        self.assertEqual(
            Notificacion.objects.filter(usuario=self.otro_director_user).count(),
            0,
        )

    def test_informe_en_revision_genera_aviso_y_nuevo_ciclo_vuelve_a_notificar(self):
        propuesta_aprobada = self._crear_propuesta(
            dias_en_revision=25,
            estado=EstadoTramite.APROBADO_EN_UP,
            codigo='PROP-INF-01',
        )
        informe = Informe.objects.create(
            propuesta=propuesta_aprobada,
            periodo_academico=self.periodo,
            codigo='INF-SEM-01',
            estado=EstadoTramite.EN_REVISION,
            fecha_envio=timezone.now() - timedelta(days=9, hours=1),
        )

        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(
            Notificacion.objects.filter(
                informe=informe,
                tipo=TIPOS_ALERTA_SEMAFORO['amarillo'],
            ).count(),
            1,
        )

        # Simula devolución y nuevo envío a revisión (nuevo ciclo)
        HistorialEstado.objects.create(
            informe=informe,
            usuario=self.director_user,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
            observacion='Ajustar conclusiones del informe.',
            tipo_accion='Solicitud de modificación',
        )
        nuevo_envio = timezone.now() - timedelta(days=8, hours=1)
        informe.fecha_envio = nuevo_envio
        informe.save(update_fields=['fecha_envio'])
        HistorialEstado.objects.create(
            informe=informe,
            usuario=self.estudiante_user,
            estado_anterior=EstadoTramite.REQUIERE_MODIFICACION,
            estado_nuevo=EstadoTramite.EN_REVISION,
            tipo_accion='Reenvío',
            fecha_hora=nuevo_envio,
        )

        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(
            Notificacion.objects.filter(
                informe=informe,
                tipo=TIPOS_ALERTA_SEMAFORO['amarillo'],
            ).count(),
            2,
        )

    def test_carrera_sin_director_activo_no_genera_avisos(self):
        carrera_sin_director = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería Civil',
            codigo='IC-SEM',
        )
        _, proceso_sin_dir = self._crear_proceso_estudiante(carrera=carrera_sin_director)
        self._crear_propuesta(
            dias_en_revision=10,
            codigo='PROP-SIN-DIR-01',
            proceso=proceso_sin_dir,
        )

        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_director_con_usuario_inactivo_no_genera_avisos(self):
        self.director_user.estado = Estado.INACTIVO
        self.director_user.save(update_fields=['estado'])
        self._crear_propuesta(dias_en_revision=10, codigo='PROP-DIR-INACT-01')

        call_command('alerta_semaforo', stdout=StringIO())
        self.assertEqual(Notificacion.objects.count(), 0)

    def test_fallo_en_ejecucion_audita_fallo_y_relanza_excepcion(self):
        self._crear_propuesta(dias_en_revision=10, codigo='PROP-FALLO-01')

        with patch(
            'apps.dashboard.management.commands.alerta_semaforo.evaluar_semaforo',
            side_effect=RuntimeError('Error simulado al calcular semáforo'),
        ):
            with self.assertRaises(RuntimeError):
                call_command('alerta_semaforo', stdout=StringIO())

        auditoria = Auditoria.objects.filter(
            tabla_afectada='notificacion',
            resultado=RESULTADO_FALLO,
        ).latest('id_auditoria')
        self.assertIsNone(auditoria.usuario)
        self.assertEqual(auditoria.resultado, RESULTADO_FALLO)
        self.assertIn('Error simulado al calcular semáforo', auditoria.detalle)
