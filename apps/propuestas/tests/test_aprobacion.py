"""SISTRA-02 · Aprobación de propuesta: pruebas automatizadas exhaustivas.

Cubre:
- Dominio y cálculos: limpieza de texto (sin borrar < ni >), semáforo (RG-07), reversión de aprobación (RN-02-04 / EX-05).
- Formularios individuales: Aprobación, Modificación, Rechazo y Reactivación.
- Formulario de acciones masivas: AccionMasivaForm (aislamiento, compatibilidad, colisiones RG-05 / EX-02).
- Vistas web y API JSON: bandeja, decisión individual, reactivación, masivo, detalle lazy y descarga.
- Casos desfavorables y de borde: ataques XSS, longitudes límite, duplicados, concurrencia y bloqueos.
"""

import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.parametrizacion.models import (
    Carrera,
    EstadoPeriodo,
    Facultad,
    Parametro,
    PeriodoAcademico,
    TipoRechazo,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    EstadoInscripcion,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.forms.aprobacion import (
    DIAS_SEMAFORO_AMARILLO,
    DIAS_SEMAFORO_VERDE,
    LONGITUD_MAXIMA_TEXTO,
    LONGITUD_MINIMA_OBSERVACION,
    MSG_02_01,
    MSG_02_02,
    MSG_02_03,
    MSG_02_04,
    MSG_02_05,
    MSG_02_06,
    MSG_02_07,
    RESULTADO_BLOQUEADO,
    AprobacionPropuestaForm,
    FiltroBandejaPropuestasForm,
    ModificacionPropuestaForm,
    PropuestaBloqueadaError,
    ReactivacionInvalidaError,
    ReactivacionPropuestaForm,
    RechazoPropuestaForm,
    aplicar_transicion,
    calcular_semaforo,
    puede_revertir_aprobacion,
    sanitizar_texto,
)
from apps.propuestas.forms.aprobacion_masiva import AccionMasivaForm
from apps.propuestas.models import ActividadCronograma, EstadoTramite, Propuesta
from apps.propuestas.views.aprobacion import ELEMENTOS_POR_PAGINA
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Permiso, Rol, RolPermiso

Usuario = get_user_model()


class BaseAprobacionTestCase(TestCase):
    """Infraestructura base de prueba para SISTRA-02."""

    def setUp(self):
        super().setUp()
        self.rol_director = Rol.objects.get(nombre='Director')
        self.rol_estudiante = Rol.objects.get(nombre='Estudiante')

        # Estructura académica
        self.facultad = Facultad.objects.create(
            nombre='Facultad de Ingenierías y Arquitectura', estado=Estado.ACTIVO
        )
        self.carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería de Sistemas',
            codigo='IS-001',
            estado=Estado.ACTIVO,
        )
        self.otra_carrera = Carrera.objects.create(
            facultad=self.facultad,
            nombre='Ingeniería Electrónica',
            codigo='IE-002',
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

        # Director
        self.user_director = Usuario.objects.create_user(
            correo_institucional='director.sistemas@unipamplona.edu.co',
            password='Password123!',
            nombre='Dr. Carlos Director',
            cedula='1098000001',
            nombre_usuario='director.sistemas',
            rol=self.rol_director,
            requiere_cambio_contrasena=False,
        )
        self.director = Director.objects.create(usuario=self.user_director)
        self.asignacion_director = DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=hoy - timedelta(days=60),
            activo=True,
        )

        # Tipos de rechazo (activo e inactivo)
        self.tipo_rechazo_activo = TipoRechazo.objects.create(
            nombre='Objetivos no alcanzables',
            descripcion='Los objetivos no se ajustan al perfil profesional.',
            estado=Estado.ACTIVO,
        )
        self.tipo_rechazo_inactivo = TipoRechazo.objects.create(
            nombre='Formato descontinuado',
            descripcion='Causal obsoleta.',
            estado=Estado.INACTIVO,
        )

        # Estudiantes e inscripciones
        self.estudiante_1 = self._crear_estudiante('1098111001', 'Estudiante Uno', self.carrera)
        self.estudiante_2 = self._crear_estudiante('1098111002', 'Estudiante Dos', self.carrera)
        self.estudiante_ajeno = self._crear_estudiante(
            '1098111003', 'Estudiante Ajeno', self.otra_carrera
        )

    def _crear_estudiante(self, cedula: str, nombre: str, carrera: Carrera) -> Estudiante:
        correo = f'{cedula}@unipamplona.edu.co'
        user = Usuario.objects.create_user(
            correo_institucional=correo,
            password='Password123!',
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=correo.split('@')[0],
            rol=self.rol_estudiante,
            requiere_cambio_contrasena=False,
        )
        estudiante = Estudiante.objects.create(usuario=user)
        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=carrera,
            fecha_registro=timezone.localdate(),
            estado=EstadoInscripcion.ACTIVO,
        )
        ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado=EstadoAvance.EN_CURSO,
        )
        return estudiante

    def crear_propuesta(
        self,
        estudiante: Estudiante,
        codigo: str,
        titulo: str = 'Propuesta de prueba',
        estado: str = EstadoTramite.EN_REVISION,
        dias_envio: int = 2,
        archivada: bool = False,
    ) -> Propuesta:
        proceso = estudiante.inscripciones.first().proceso
        fecha_envio = timezone.now() - timedelta(days=dias_envio) if dias_envio is not None else None
        return Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=self.periodo,
            codigo=codigo,
            titulo=titulo,
            resena_historica='Reseña histórica válida para la prueba.',
            identificacion_necesidad='Necesidad identificada clara y precisa.',
            justificacion='Justificación detallada con suficiente longitud.',
            objetivos='Objetivo general y específicos bien definidos.',
            referente_teorico='Marco teórico de referencia adecuado.',
            impacto_social='Impacto social directo en la comunidad.',
            identificacion_poblacion='Población objetivo identificada.',
            propuesta_social='Propuesta de intervención social.',
            entidad='Fundación Social Pamplona',
            poblacion_beneficiada='100 familias vulnerables',
            zona='Urbana',
            area='Tecnología social',
            sector='Comunitario',
            unidad='Barrio Central',
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate() + timedelta(days=60),
            estado=estado,
            fecha_envio=fecha_envio,
            archivada=archivada,
        )


# ==============================================================================
# 1. Pruebas de Dominio, Sanitización, Semáforo y Reglas de Reversión
# ==============================================================================
class TestDominioYSemaforo(BaseAprobacionTestCase):
    """Pruebas unitarias de las funciones de soporte del dominio de aprobación."""

    def test_sanitizar_texto_conserva_simbolos_menor_y_mayor(self):
        """Solo quita espacios: no borra texto entre < y > (el escape ocurre al mostrar)."""
        texto = '  La población debe ser < 50 personas y > 10 por jornada  '
        self.assertEqual(
            sanitizar_texto(texto),
            'La población debe ser < 50 personas y > 10 por jornada',
        )
        self.assertEqual(
            sanitizar_texto('Revisar <img src=x onerror=alert(1)> antes de aprobar'),
            'Revisar <img src=x onerror=alert(1)> antes de aprobar',
        )

        ejemplo_revisor = "Revise la sección 'Objetivos' y Peña & Cía"
        self.assertEqual(sanitizar_texto(ejemplo_revisor), "Revise la sección 'Objetivos' y Peña & Cía")

    def test_sanitizar_texto_vacios_y_espacios(self):
        """Maneja correctamente cadenas vacías, None o únicamente con espacios."""
        self.assertEqual(sanitizar_texto(''), '')
        self.assertEqual(sanitizar_texto('   \n\t  '), '')
        self.assertEqual(sanitizar_texto(None), '')

    def test_calcular_semaforo_verde_0_a_7_dias(self):
        """El semáforo es verde de 0 a 7 días en estado 'En revisión' (RG-07)."""
        prop_0_dias = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-0', dias_envio=0)
        sem_0 = calcular_semaforo(prop_0_dias)
        self.assertEqual(sem_0['color'], 'verde')
        self.assertEqual(sem_0['dias'], 0)
        self.assertFalse(sem_0['pausado'])

        prop_7_dias = self.crear_propuesta(self.estudiante_2, 'PROP-SEM-7', dias_envio=7)
        sem_7 = calcular_semaforo(prop_7_dias)
        self.assertEqual(sem_7['color'], 'verde')
        self.assertEqual(sem_7['dias'], 7)
        self.assertFalse(sem_7['pausado'])

    def test_calcular_semaforo_amarillo_8_a_14_dias(self):
        """El semáforo es amarillo de 8 a 14 días corridos (RG-07)."""
        prop_8_dias = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-8', dias_envio=8)
        sem_8 = calcular_semaforo(prop_8_dias)
        self.assertEqual(sem_8['color'], 'amarillo')
        self.assertEqual(sem_8['dias'], 8)
        self.assertFalse(sem_8['pausado'])

        prop_14_dias = self.crear_propuesta(self.estudiante_2, 'PROP-SEM-14', dias_envio=14)
        sem_14 = calcular_semaforo(prop_14_dias)
        self.assertEqual(sem_14['color'], 'amarillo')
        self.assertEqual(sem_14['dias'], 14)
        self.assertFalse(sem_14['pausado'])

    def test_calcular_semaforo_rojo_15_o_mas_dias(self):
        """El semáforo es rojo a partir de 15 días corridos (RG-07)."""
        prop_15_dias = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-15', dias_envio=15)
        sem_15 = calcular_semaforo(prop_15_dias)
        self.assertEqual(sem_15['color'], 'rojo')
        self.assertEqual(sem_15['dias'], 15)
        self.assertFalse(sem_15['pausado'])

    def test_calcular_semaforo_parametrizado_desde_bd(self):
        """El semáforo adopta los umbrales configurados en la tabla Parametro (BD)."""
        Parametro.objects.create(
            clave='dias_semaforo_verde',
            valor='4',
            usuario_actualizacion=self.user_director,
        )
        Parametro.objects.create(
            clave='dias_semaforo_amarillo',
            valor='9',
            usuario_actualizacion=self.user_director,
        )
        prop = self.crear_propuesta(self.estudiante_1, 'P-SEM-BD', dias_envio=4)
        self.assertEqual(calcular_semaforo(prop)['color'], 'verde')

        prop.fecha_envio = timezone.now() - timedelta(days=5)
        self.assertEqual(calcular_semaforo(prop)['color'], 'amarillo')

        prop.fecha_envio = timezone.now() - timedelta(days=10)
        self.assertEqual(calcular_semaforo(prop)['color'], 'rojo')

    def test_calcular_semaforo_pausado_en_otros_estados(self):
        """El semáforo se detiene cuando la propuesta sale de 'En revisión' (RG-07)."""
        prop = self.crear_propuesta(self.estudiante_1, 'P-PAUSA-1', dias_envio=20)
        for estado in [
            EstadoTramite.APROBADO,
            EstadoTramite.REQUIERE_MODIFICACION,
            EstadoTramite.RECHAZADO,
            EstadoTramite.BORRADOR,
        ]:
            prop.estado = estado
            sem = calcular_semaforo(prop)
            self.assertEqual(sem['color'], 'neutro')
            self.assertTrue(sem['pausado'])
            self.assertIn('Semáforo detenido', sem['tooltip'])

    def test_calcular_semaforo_tolerante_a_fecha_envio_nula(self):
        """Si fecha_envio es nula, calcula con fecha_creacion sin lanzar excepción."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-ENV-NULO', dias_envio=None)
        prop.fecha_envio = None
        prop.save()
        sem = calcular_semaforo(prop)
        self.assertGreaterEqual(sem['dias'], 0)
        self.assertEqual(sem['color'], 'verde')

    def test_puede_revertir_aprobacion_sin_cargues_ni_informes(self):
        """Permite revertir si no existe cargue en UP ni informe (RN-02-04)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REV-OK', estado=EstadoTramite.APROBADO
        )
        puede, motivo = puede_revertir_aprobacion(prop)
        self.assertTrue(puede)
        self.assertEqual(motivo, '')

    def test_puede_revertir_bloqueada_por_cargue_up_pendiente_o_aprobado(self):
        """Bloquea reversión si el estudiante pulsó Subido en UP (RN-02-04 / EX-05)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REV-BLOQ-1', estado=EstadoTramite.APROBADO
        )
        CargueUp.objects.create(
            propuesta=prop,
            estado_verificacion=EstadoVerificacion.PENDIENTE,
        )
        puede, motivo = puede_revertir_aprobacion(prop)
        self.assertFalse(puede)
        self.assertEqual(motivo, MSG_02_07)

        # Si el cargue ya fue Aprobado en UP, también debe estar bloqueada
        cargue = CargueUp.objects.get(propuesta=prop)
        cargue.estado_verificacion = EstadoVerificacion.APROBADO_EN_UP
        cargue.save()
        puede_aprobado, _ = puede_revertir_aprobacion(prop)
        self.assertFalse(puede_aprobado)

    def test_puede_revertir_permitida_si_cargue_up_fue_rechazado_en_up(self):
        """Permite revertir si el cargue fue Rechazado en UP y no hay uno nuevo (RN-02-04)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REV-RECH-UP', estado=EstadoTramite.APROBADO
        )
        CargueUp.objects.create(
            propuesta=prop,
            estado_verificacion=EstadoVerificacion.RECHAZADO_EN_UP,
            observacion='Rechazado en UP por falta de firma.',
        )
        puede, motivo = puede_revertir_aprobacion(prop)
        self.assertTrue(puede)
        self.assertEqual(motivo, '')

    def test_puede_revertir_bloqueada_por_informe_iniciado(self):
        """Bloquea reversión si existe un informe registrado para la propuesta (RN-02-04)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REV-BLOQ-INF', estado=EstadoTramite.APROBADO
        )
        Informe.objects.create(
            propuesta=prop,
            periodo_academico=self.periodo,
            codigo='INF-001',
            estado=EstadoTramite.BORRADOR,
        )
        puede, motivo = puede_revertir_aprobacion(prop)
        self.assertFalse(puede)
        self.assertEqual(motivo, MSG_02_07)


# ==============================================================================
# 2. Pruebas del Formulario de Filtros de la Bandeja
# ==============================================================================
class TestFiltroBandejaPropuestasForm(BaseAprobacionTestCase):
    """Pruebas del formulario de búsqueda y filtros superiores."""

    def test_filtro_vacio_es_valido(self):
        """El formulario vacío es válido para mostrar la lista completa."""
        form = FiltroBandejaPropuestasForm(data={})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['buscar'], '')
        self.assertEqual(form.cleaned_data['estado'], '')
        self.assertEqual(form.cleaned_data['semaforo'], '')

    def test_filtro_sanitiza_busqueda_y_acepta_opciones_validas(self):
        """Recorta el texto de búsqueda y valida opciones de los selectores."""
        data = {
            'buscar': "<script>alert(1)</script> Juan Pérez ",
            'estado': EstadoTramite.EN_REVISION,
            'semaforo': 'amarillo',
        }
        form = FiltroBandejaPropuestasForm(data=data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['buscar'], '<script>alert(1)</script> Juan Pérez')
        self.assertEqual(form.cleaned_data['estado'], EstadoTramite.EN_REVISION)
        self.assertEqual(form.cleaned_data['semaforo'], 'amarillo')

    def test_filtro_rechaza_opcion_invalida_de_estado_o_semaforo(self):
        """Rechaza opciones inexistentes en los desplegables de estado o semáforo."""
        form = FiltroBandejaPropuestasForm(data={'estado': 'ESTADO_INVENTADO'})
        self.assertFalse(form.is_valid())
        self.assertIn('estado', form.errors)

        form_sem = FiltroBandejaPropuestasForm(data={'semaforo': 'azul'})
        self.assertFalse(form_sem.is_valid())
        self.assertIn('semaforo', form_sem.errors)

    def test_filtro_bandeja_opciones_semaforo_dinamicas_desde_bd(self):
        """Las opciones del selector de semáforo se construyen dinámicamente según Parametro."""
        Parametro.objects.create(
            clave='dias_semaforo_verde',
            valor='5',
            usuario_actualizacion=self.user_director,
        )
        Parametro.objects.create(
            clave='dias_semaforo_amarillo',
            valor='12',
            usuario_actualizacion=self.user_director,
        )
        form = FiltroBandejaPropuestasForm()
        choices = dict(form.fields['semaforo'].choices)
        self.assertEqual(choices['verde'], 'Verde (0 a 5 días)')
        self.assertEqual(choices['amarillo'], 'Amarillo (6 a 12 días)')
        self.assertEqual(choices['rojo'], 'Rojo (13+ días)')


# ==============================================================================
# 3. Pruebas de Aprobación Individual (AprobacionPropuestaForm)
# ==============================================================================
class TestAprobacionPropuestaForm(BaseAprobacionTestCase):
    """Pruebas del formulario de aprobación individual."""

    def test_aprobar_exito_sin_observacion(self):
        """Aprueba con éxito sin observación (observación opcional)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-APR-1')
        form = AprobacionPropuestaForm(data={'observacion': ''})
        self.assertTrue(form.is_valid())

        form.procesar(prop, self.user_director)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)

        # Historial de estado
        hist = HistorialEstado.objects.filter(propuesta=prop).latest('id_historial')
        self.assertEqual(hist.estado_anterior, EstadoTramite.EN_REVISION)
        self.assertEqual(hist.estado_nuevo, EstadoTramite.APROBADO)
        self.assertEqual(hist.tipo_accion, 'Aprobación')
        self.assertEqual(hist.usuario, self.user_director)

        # Notificación y Auditoría
        notif = Notificacion.objects.filter(propuesta=prop).latest('id_notificacion')
        self.assertIn('Aprobado', notif.mensaje)
        audit = Auditoria.objects.filter(id_registro_afectado=prop.pk).latest('id_auditoria')
        self.assertEqual(audit.accion, 'APROBAR_PROPUESTA')
        self.assertEqual(audit.resultado, 'Éxito')

    def test_aprobar_exito_con_observacion(self):
        """Aprueba con éxito guardando la observación tal cual (se escapa al mostrarla)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-APR-2')
        obs = '<b>Felicitaciones</b>, propuesta excelente para la comunidad.'
        form = AprobacionPropuestaForm(data={'observacion': obs})
        self.assertTrue(form.is_valid())

        form.procesar(prop, self.user_director)
        hist = HistorialEstado.objects.filter(propuesta=prop).latest('id_historial')
        self.assertEqual(hist.observacion, obs)

    def test_aprobar_falla_observacion_mayor_a_1000_caracteres(self):
        """Falla si la observación supera el límite de 1000 caracteres (Tabla 8)."""
        form = AprobacionPropuestaForm(data={'observacion': 'A' * 1001})
        self.assertFalse(form.is_valid())
        self.assertIn('observacion', form.errors)

    def test_aprobar_idempotente_si_ya_estaba_aprobada(self):
        """No genera registros duplicados si la propuesta ya estaba Aprobada (EX-01)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-APR-IDEM', estado=EstadoTramite.APROBADO
        )
        total_hist_antes = HistorialEstado.objects.filter(propuesta=prop).count()
        form = AprobacionPropuestaForm(data={'observacion': 'Re-aprobar'})
        self.assertTrue(form.is_valid())
        form.procesar(prop, self.user_director)
        self.assertEqual(HistorialEstado.objects.filter(propuesta=prop).count(), total_hist_antes)

    def test_aprobar_falla_si_propuesta_esta_en_rechazado(self):
        """Bloquea aprobación directa si la propuesta está en Rechazado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-APR-REC', estado=EstadoTramite.RECHAZADO
        )
        form = AprobacionPropuestaForm(data={'observacion': ''})
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError) as ctx:
            form.procesar(prop, self.user_director)
        self.assertIn('modal de reactivación', str(ctx.exception))


# ==============================================================================
# 4. Pruebas de Modificación Individual (ModificacionPropuestaForm)
# ==============================================================================
class TestModificacionPropuestaForm(BaseAprobacionTestCase):
    """Pruebas del formulario de solicitud de correcciones (Requiere modificación)."""

    def test_modificar_exito_con_observacion_valida(self):
        """Solicita modificación con observación de 10 a 1000 caracteres (RN-02-02)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-MOD-1')
        obs = 'Ajustar la sección 3 del cronograma y ampliar beneficiarios.'
        form = ModificacionPropuestaForm(data={'observacion': obs})
        self.assertTrue(form.is_valid())

        form.procesar(prop, self.user_director)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.REQUIERE_MODIFICACION)

        hist = HistorialEstado.objects.filter(propuesta=prop).latest('id_historial')
        self.assertEqual(hist.tipo_accion, 'Solicitud de modificación')
        self.assertEqual(hist.observacion, obs)

        audit = Auditoria.objects.filter(id_registro_afectado=prop.pk).latest('id_auditoria')
        self.assertEqual(audit.accion, 'SOLICITAR_MODIFICACION_PROPUESTA')
        self.assertEqual(audit.resultado, 'Éxito')

    def test_modificar_falla_observacion_vacia_o_menor_a_10_caracteres(self):
        """Falla si la observación está vacía o tiene menos de 10 caracteres."""
        # Vacía
        form_vacio = ModificacionPropuestaForm(data={'observacion': ''})
        self.assertFalse(form_vacio.is_valid())
        self.assertIn('observacion', form_vacio.errors)

        # 9 caracteres
        form_corta = ModificacionPropuestaForm(data={'observacion': '123456789'})
        self.assertFalse(form_corta.is_valid())
        self.assertIn('observacion', form_corta.errors)

        # 10 caracteres exactos (límite inferior válido)
        form_limite = ModificacionPropuestaForm(data={'observacion': '1234567890'})
        self.assertTrue(form_limite.is_valid())

    def test_modificar_falla_observacion_mayor_a_1000_caracteres(self):
        """Falla si supera los 1000 caracteres permitidos."""
        form = ModificacionPropuestaForm(data={'observacion': 'A' * 1001})
        self.assertFalse(form.is_valid())
        self.assertIn('observacion', form.errors)

    def test_modificar_reversion_desde_aprobado_exito(self):
        """Permite cambiar desde Aprobado a Requiere modificación si no hay bloqueo."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-MOD-REV-OK', estado=EstadoTramite.APROBADO
        )
        form = ModificacionPropuestaForm(
            data={'observacion': 'Se detectó inconsistencia previa a la carga en UP.'}
        )
        self.assertTrue(form.is_valid())
        form.procesar(prop, self.user_director)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.REQUIERE_MODIFICACION)

    def test_modificar_reversion_desde_aprobado_bloqueado_por_cargue_up(self):
        """Bloquea cambio si tiene CargueUp pendiente o aprobado (RN-02-04 / EX-05)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-MOD-BLOQ', estado=EstadoTramite.APROBADO
        )
        CargueUp.objects.create(
            propuesta=prop, estado_verificacion=EstadoVerificacion.PENDIENTE
        )
        form = ModificacionPropuestaForm(data={'observacion': 'Intento revertir pero ya subió.'})
        self.assertTrue(form.is_valid())

        with self.assertRaises(PropuestaBloqueadaError):
            form.procesar(prop, self.user_director)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)

        # Se registra en auditoría el intento bloqueado
        audit = Auditoria.objects.filter(
            id_registro_afectado=prop.pk, accion='MODIFICAR_PROPUESTA_BLOQUEADA'
        ).latest('id_auditoria')
        self.assertEqual(audit.resultado, 'Bloqueado')

    def test_modificar_falla_si_esta_en_rechazado(self):
        """Bloquea modificación directa de una propuesta rechazada."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-MOD-REC', estado=EstadoTramite.RECHAZADO
        )
        form = ModificacionPropuestaForm(data={'observacion': 'Modificar rechazada sin reactivar.'})
        self.assertTrue(form.is_valid())
        with self.assertRaises(ValidationError):
            form.procesar(prop, self.user_director)


# ==============================================================================
# 5. Pruebas de Rechazo Individual (RechazoPropuestaForm)
# ==============================================================================
class TestRechazoPropuestaForm(BaseAprobacionTestCase):
    """Pruebas del formulario de rechazo individual (RN-02-01)."""

    def test_rechazo_exito_con_tipo_y_observacion_validos(self):
        """Rechaza con éxito vinculando causal activa y observación (RN-02-01)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-REC-1')
        obs = 'El proyecto no cumple con los lineamientos comunitarios requeridos.'
        form = RechazoPropuestaForm(
            data={'tipo_rechazo': self.tipo_rechazo_activo.pk, 'observacion': obs}
        )
        self.assertTrue(form.is_valid())

        form.procesar(prop, self.user_director)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.RECHAZADO)

        hist = HistorialEstado.objects.filter(propuesta=prop).latest('id_historial')
        self.assertEqual(hist.tipo_rechazo, self.tipo_rechazo_activo)
        self.assertEqual(hist.tipo_accion, 'Rechazo')
        self.assertEqual(hist.observacion, obs)

        audit = Auditoria.objects.filter(id_registro_afectado=prop.pk).latest('id_auditoria')
        self.assertEqual(audit.accion, 'RECHAZAR_PROPUESTA')
        self.assertEqual(audit.resultado, 'Éxito')

    def test_rechazo_falla_sin_tipo_rechazo(self):
        """Es obligatorio seleccionar un tipo de rechazo (RN-02-01)."""
        form = RechazoPropuestaForm(
            data={'tipo_rechazo': '', 'observacion': 'Observación válida de más de diez.'}
        )
        self.assertFalse(form.is_valid())
        self.assertIn('tipo_rechazo', form.errors)

    def test_rechazo_falla_con_tipo_rechazo_inactivo(self):
        """No permite causales de rechazo inactivas."""
        form = RechazoPropuestaForm(
            data={
                'tipo_rechazo': self.tipo_rechazo_inactivo.pk,
                'observacion': 'Observación válida de más de diez.',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('tipo_rechazo', form.errors)

    def test_rechazo_falla_observacion_invalida(self):
        """Falla si la observación es menor a 10 o mayor a 1000 caracteres."""
        form_vacio = RechazoPropuestaForm(
            data={'tipo_rechazo': self.tipo_rechazo_activo.pk, 'observacion': ''}
        )
        self.assertFalse(form_vacio.is_valid())

        form_corta = RechazoPropuestaForm(
            data={'tipo_rechazo': self.tipo_rechazo_activo.pk, 'observacion': '123456789'}
        )
        self.assertFalse(form_corta.is_valid())

        form_larga = RechazoPropuestaForm(
            data={'tipo_rechazo': self.tipo_rechazo_activo.pk, 'observacion': 'A' * 1001}
        )
        self.assertFalse(form_larga.is_valid())

    def test_rechazo_desde_aprobado_bloqueado_por_cargue_up(self):
        """Rechazo desde Aprobado se bloquea si el estudiante ya pulsó Subido en UP (RN-02-04)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REC-BLOQ', estado=EstadoTramite.APROBADO
        )
        CargueUp.objects.create(
            propuesta=prop, estado_verificacion=EstadoVerificacion.PENDIENTE
        )
        form = RechazoPropuestaForm(
            data={
                'tipo_rechazo': self.tipo_rechazo_activo.pk,
                'observacion': 'Rechazar propuesta ya subida en UP.',
            }
        )
        self.assertTrue(form.is_valid())

        with self.assertRaises(PropuestaBloqueadaError):
            form.procesar(prop, self.user_director)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)


# ==============================================================================
# 6. Pruebas de Reactivación Individual (ReactivacionPropuestaForm)
# ==============================================================================
class TestReactivacionPropuestaForm(BaseAprobacionTestCase):
    """Pruebas de la reactivación de propuestas rechazadas por error (RG-04 / RG-05)."""

    def test_reactivar_exito_retorna_a_en_revision(self):
        """Reactiva y retorna la propuesta a 'En revisión' con su justificación."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REA-1', estado=EstadoTramite.RECHAZADO, dias_envio=5
        )
        motivo = 'Se rechazó por confusión con otro documento; el contenido es válido.'
        form = ReactivacionPropuestaForm(data={'motivo_reactivacion': motivo})
        self.assertTrue(form.is_valid())

        form.procesar(prop, self.user_director)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)

        hist = HistorialEstado.objects.filter(propuesta=prop).latest('id_historial')
        self.assertEqual(hist.tipo_accion, 'Reactivación')
        self.assertEqual(hist.estado_anterior, EstadoTramite.RECHAZADO)
        self.assertEqual(hist.estado_nuevo, EstadoTramite.EN_REVISION)
        self.assertEqual(hist.motivo_reactivacion, motivo)

        # Semáforo se reactiva conservando los días que llevaba al rechazarse
        sem = calcular_semaforo(prop)
        self.assertFalse(sem['pausado'])
        self.assertEqual(sem['dias'], 5)
        self.assertEqual(sem['color'], 'verde')

    def test_reactivar_falla_si_propuesta_esta_archivada(self):
        """Propuesta archivada no puede reactivarse por políticas de conservación."""
        prop = self.crear_propuesta(
            self.estudiante_1,
            'PROP-REA-ARCH',
            estado=EstadoTramite.RECHAZADO,
            archivada=True,
        )
        form = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'Justificación válida de reactivación.'}
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ReactivacionInvalidaError) as ctx:
            form.procesar(prop, self.user_director)
        self.assertIn('archivada', str(ctx.exception))

        # Intento registrado una sola vez en auditoría como Bloqueado, con el motivo
        audit = Auditoria.objects.get(id_registro_afectado=prop.pk)
        self.assertEqual(audit.accion, 'REACTIVAR_PROPUESTA_BLOQUEADA')
        self.assertEqual(audit.resultado, 'Bloqueado')
        self.assertIn('archivada', audit.detalle)
        self.assertIn('Justificación válida de reactivación.', audit.detalle)

    def test_reactivar_falla_si_estudiante_ya_tiene_otra_propuesta_activa_rg05(self):
        """Regla RG-05 / EX-02: Bloquea reactivación si el estudiante ya tiene una propuesta activa."""
        # 1. Propuesta rechazada que se pretende reactivar
        prop_rechazada = self.crear_propuesta(
            self.estudiante_1, 'PROP-REA-COL-1', estado=EstadoTramite.RECHAZADO
        )
        # 2. El estudiante ya radicó otra propuesta que está en revisión
        self.crear_propuesta(
            self.estudiante_1, 'PROP-REA-COL-2', estado=EstadoTramite.EN_REVISION
        )

        form = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'Intentando reactivar teniendo otra activa.'}
        )
        self.assertTrue(form.is_valid())

        with self.assertRaises(ReactivacionInvalidaError) as ctx:
            form.procesar(prop_rechazada, self.user_director)

        self.assertIn(self.estudiante_1.usuario.nombre, str(ctx.exception))

        # Intento registrado en auditoría como Bloqueado
        audit = Auditoria.objects.get(id_registro_afectado=prop_rechazada.pk)
        self.assertEqual(audit.accion, 'REACTIVAR_PROPUESTA_BLOQUEADA')
        self.assertEqual(audit.resultado, 'Bloqueado')
        self.assertIn(self.estudiante_1.usuario.nombre, audit.detalle)

    def test_reactivar_falla_justificacion_invalida(self):
        """Falla si el motivo de reactivación tiene menos de 10 o más de 1000 caracteres."""
        form_vacio = ReactivacionPropuestaForm(data={'motivo_reactivacion': ''})
        self.assertFalse(form_vacio.is_valid())

        form_corta = ReactivacionPropuestaForm(data={'motivo_reactivacion': '123456789'})
        self.assertFalse(form_corta.is_valid())

        form_larga = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'A' * 1001}
        )
        self.assertFalse(form_larga.is_valid())

    def test_reactivar_bloquea_propuestas_que_no_estan_en_rechazado(self):
        """Si la propuesta no está en Rechazado, se bloquea, no cambia nada y queda auditado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REA-IGN', estado=EstadoTramite.EN_REVISION
        )
        total_hist_antes = HistorialEstado.objects.filter(propuesta=prop).count()
        form = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'Justificación para propuesta no rechazada.'}
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ReactivacionInvalidaError):
            form.procesar(prop, self.user_director)
        self.assertEqual(HistorialEstado.objects.filter(propuesta=prop).count(), total_hist_antes)
        audit = Auditoria.objects.get(id_registro_afectado=prop.pk)
        self.assertEqual(audit.resultado, 'Bloqueado')
        self.assertIn('Transición: En revisión -> En revisión', audit.detalle)

    def test_reactivar_bloquea_si_otro_proceso_ya_cambio_el_estado(self):
        """Usa el estado real de la BD: una instancia desactualizada no aparenta éxito."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REA-CARRERA', estado=EstadoTramite.RECHAZADO
        )
        Propuesta.objects.filter(pk=prop.pk).update(estado=EstadoTramite.EN_REVISION)
        form = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'Justificación con instancia desactualizada.'}
        )
        self.assertTrue(form.is_valid())
        with self.assertRaises(ReactivacionInvalidaError):
            form.procesar(prop, self.user_director)
        audit = Auditoria.objects.get(id_registro_afectado=prop.pk)
        self.assertEqual(audit.resultado, 'Bloqueado')
        self.assertIn('Transición: En revisión -> En revisión', audit.detalle)


# ==============================================================================
# 7. Pruebas de Acciones Masivas (AccionMasivaForm)
# ==============================================================================
class TestAccionMasivaForm(BaseAprobacionTestCase):
    """Pruebas del formulario de acciones masivas en lote (FA-03)."""

    def test_masivo_falla_sin_seleccion(self):
        """Falla si no se seleccionó ninguna propuesta."""
        form = AccionMasivaForm(data={'accion': 'aprobar', 'propuestas_ids': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('propuestas_ids', form.errors)

    def test_masivo_limpia_ids_con_espacios_y_tokens_invalidos(self):
        """Limpia correctamente la lista de IDs eliminando espacios y caracteres no numéricos."""
        form = AccionMasivaForm(
            data={'accion': 'aprobar', 'propuestas_ids': ' 10, 20 , texto , 30 '}
        )
        form.is_valid()
        self.assertEqual(form.cleaned_data['propuestas_ids'], [10, 20, 30])

    def test_masivo_soporta_multiples_inputs_getlist(self):
        """Soporta que el navegador envíe múltiples inputs con el mismo nombre 'propuestas_ids'."""
        from django.http import QueryDict

        qdict = QueryDict(mutable=True)
        qdict['accion'] = 'aprobar'
        qdict.appendlist('propuestas_ids', '10')
        qdict.appendlist('propuestas_ids', '20')
        qdict.appendlist('propuestas_ids', '30')

        form = AccionMasivaForm(data=qdict)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['propuestas_ids'], [10, 20, 30])

    def test_masivo_falla_si_propuestas_pertenecen_a_otra_carrera(self):
        """Aislamiento por carrera: Falla si se intenta procesar una propuesta de otra carrera."""
        prop_propia = self.crear_propuesta(self.estudiante_1, 'PROP-MAS-PROPIA')
        prop_ajena = self.crear_propuesta(self.estudiante_ajeno, 'PROP-MAS-AJENA')

        form = AccionMasivaForm(
            data={
                'accion': 'aprobar',
                'propuestas_ids': f'{prop_propia.pk},{prop_ajena.pk}',
            }
        )
        self.assertTrue(form.is_valid())

        with self.assertRaises(ValidationError) as ctx:
            form.procesar(self.carrera, self.user_director)
        self.assertIn('carrera activa del Director', str(ctx.exception))

    def test_masivo_aprobar_exito(self):
        """Aprobación masiva de múltiples propuestas en 'En revisión'."""
        prop1 = self.crear_propuesta(self.estudiante_1, 'PROP-MAS-APR-1')
        prop2 = self.crear_propuesta(self.estudiante_2, 'PROP-MAS-APR-2')

        form = AccionMasivaForm(
            data={
                'accion': 'aprobar',
                'propuestas_ids': f'{prop1.pk},{prop2.pk}',
                'observacion': 'Aprobadas en bloque por el comité.',
            }
        )
        self.assertTrue(form.is_valid())

        procesadas = form.procesar(self.carrera, self.user_director)
        self.assertEqual(procesadas, 2)

        prop1.refresh_from_db()
        prop2.refresh_from_db()
        self.assertEqual(prop1.estado, EstadoTramite.APROBADO)
        self.assertEqual(prop2.estado, EstadoTramite.APROBADO)

    def test_masivo_aprobar_falla_con_estados_mixtos_rn0203(self):
        """Para aprobar masivamente, todas deben estar exclusivamente en 'En revisión'."""
        prop1 = self.crear_propuesta(self.estudiante_1, 'PROP-MAS-MIX-1', estado=EstadoTramite.EN_REVISION)
        prop2 = self.crear_propuesta(
            self.estudiante_2, 'PROP-MAS-MIX-2', estado=EstadoTramite.REQUIERE_MODIFICACION
        )

        form = AccionMasivaForm(
            data={'accion': 'aprobar', 'propuestas_ids': f'{prop1.pk},{prop2.pk}'}
        )
        self.assertTrue(form.is_valid())

        with self.assertRaises(ValidationError) as ctx:
            form.procesar(self.carrera, self.user_director)
        self.assertIn("exclusivamente en estado 'En revisión'", str(ctx.exception))

    def test_masivo_rechazar_exito(self):
        """Rechazo masivo con causal y observación obligatorias."""
        prop1 = self.crear_propuesta(self.estudiante_1, 'PROP-MAS-REC-1')
        prop2 = self.crear_propuesta(self.estudiante_2, 'PROP-MAS-REC-2')

        obs = 'Rechazo masivo por vencimiento de plazo institucional.'
        form = AccionMasivaForm(
            data={
                'accion': 'rechazar',
                'propuestas_ids': f'{prop1.pk},{prop2.pk}',
                'tipo_rechazo': self.tipo_rechazo_activo.pk,
                'observacion': obs,
            }
        )
        self.assertTrue(form.is_valid())

        procesadas = form.procesar(self.carrera, self.user_director)
        self.assertEqual(procesadas, 2)

        prop1.refresh_from_db()
        prop2.refresh_from_db()
        self.assertEqual(prop1.estado, EstadoTramite.RECHAZADO)
        self.assertEqual(prop2.estado, EstadoTramite.RECHAZADO)

    def test_masivo_rechazar_falla_sin_causal_o_sin_observacion(self):
        """Rechazar masivo requiere tipo_rechazo y observación mínima de 10 caracteres."""
        form_sin_causal = AccionMasivaForm(
            data={
                'accion': 'rechazar',
                'propuestas_ids': '1,2',
                'observacion': 'Observación válida pero sin causal.',
            }
        )
        self.assertFalse(form_sin_causal.is_valid())
        self.assertIn('tipo_rechazo', form_sin_causal.errors)

        form_sin_obs = AccionMasivaForm(
            data={
                'accion': 'rechazar',
                'propuestas_ids': '1,2',
                'tipo_rechazo': self.tipo_rechazo_activo.pk,
                'observacion': '',
            }
        )
        self.assertFalse(form_sin_obs.is_valid())
        self.assertIn('observacion', form_sin_obs.errors)

    def test_masivo_reactivar_exito(self):
        """Reactivación masiva de propuestas rechazadas con justificación."""
        prop1 = self.crear_propuesta(
            self.estudiante_1, 'PROP-MAS-REA-1', estado=EstadoTramite.RECHAZADO
        )
        prop2 = self.crear_propuesta(
            self.estudiante_2, 'PROP-MAS-REA-2', estado=EstadoTramite.RECHAZADO
        )

        motivo = 'Reactivación masiva tras ajuste de criterios de evaluación.'
        form = AccionMasivaForm(
            data={
                'accion': 'reactivar',
                'propuestas_ids': f'{prop1.pk},{prop2.pk}',
                'observacion': motivo,
            }
        )
        self.assertTrue(form.is_valid())

        procesadas = form.procesar(self.carrera, self.user_director)
        self.assertEqual(procesadas, 2)

        prop1.refresh_from_db()
        prop2.refresh_from_db()
        self.assertEqual(prop1.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(prop2.estado, EstadoTramite.EN_REVISION)

    def test_masivo_reactivar_falla_colision_rg05_en_el_mismo_lote(self):
        """Falla si en la selección masiva van dos propuestas del mismo estudiante (RG-05)."""
        prop_rec_1 = self.crear_propuesta(
            self.estudiante_1, 'PROP-LOTE-DUP-1', estado=EstadoTramite.RECHAZADO
        )
        prop_rec_2 = self.crear_propuesta(
            self.estudiante_1, 'PROP-LOTE-DUP-2', estado=EstadoTramite.RECHAZADO
        )

        form = AccionMasivaForm(
            data={
                'accion': 'reactivar',
                'propuestas_ids': f'{prop_rec_1.pk},{prop_rec_2.pk}',
                'observacion': 'Reactivar dos del mismo estudiante.',
            }
        )
        self.assertTrue(form.is_valid())

        with self.assertRaises(ReactivacionInvalidaError) as ctx:
            form.procesar(self.carrera, self.user_director)
        self.assertIn(self.estudiante_1.usuario.nombre, str(ctx.exception))

    def test_masivo_reactivar_falla_colision_rg05_con_propuesta_activa_en_db(self):
        """Falla en consulta por lotes si algún estudiante ya tiene otra propuesta activa en BD."""
        prop_rec = self.crear_propuesta(
            self.estudiante_1, 'PROP-MAS-BD-REC', estado=EstadoTramite.RECHAZADO
        )
        # El estudiante ya tiene otra activa en BD
        self.crear_propuesta(
            self.estudiante_1, 'PROP-MAS-BD-ACT', estado=EstadoTramite.EN_REVISION
        )

        form = AccionMasivaForm(
            data={
                'accion': 'reactivar',
                'propuestas_ids': f'{prop_rec.pk}',
                'observacion': 'Justificación para reactivación masiva.',
            }
        )
        self.assertTrue(form.is_valid())

        with self.assertRaises(ReactivacionInvalidaError) as ctx:
            form.procesar(self.carrera, self.user_director)
        self.assertIn(self.estudiante_1.usuario.nombre, str(ctx.exception))


class TestAccionMasivaBloqueosAuditados(BaseAprobacionTestCase):
    """Todo intento masivo bloqueado deja auditoría con resultado Bloqueado (BRD SISTRA-02)."""

    def _procesar_bloqueado(self, data: dict, excepcion=ValidationError) -> None:
        form = AccionMasivaForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(excepcion):
            form.procesar(self.carrera, self.user_director)

    def _bloqueos(self, accion: str):
        return Auditoria.objects.filter(accion=accion, resultado=RESULTADO_BLOQUEADO)

    def test_estados_mixtos_audita_una_fila_por_propuesta_del_lote(self):
        """Aprobar en lote con estados incompatibles: una fila Bloqueado por propuesta, sin cambios."""
        prop1 = self.crear_propuesta(self.estudiante_1, 'PROP-AUD-MIX-1')
        prop2 = self.crear_propuesta(
            self.estudiante_2, 'PROP-AUD-MIX-2', estado=EstadoTramite.REQUIERE_MODIFICACION
        )

        self._procesar_bloqueado(
            {'accion': 'aprobar', 'propuestas_ids': f'{prop1.pk},{prop2.pk}', 'observacion': 'Lote mixto'}
        )

        filas = self._bloqueos('APROBACION_MASIVA_BLOQUEADA')
        self.assertEqual(
            sorted(filas.values_list('id_registro_afectado', flat=True)), sorted([prop1.pk, prop2.pk])
        )
        detalle = filas.get(id_registro_afectado=prop2.pk).detalle
        self.assertIn(self.estudiante_2.usuario.cedula, detalle)
        self.assertIn('Requiere modificación -> Aprobado', detalle)
        self.assertIn("exclusivamente en estado 'En revisión'", detalle)
        self.assertTrue(all(f.usuario_id == self.user_director.pk for f in filas))
        prop1.refresh_from_db()
        self.assertEqual(prop1.estado, EstadoTramite.EN_REVISION)

    def test_propuestas_de_otra_carrera_auditan_sin_datos_del_estudiante_ajeno(self):
        """IDs ajenos: se bloquea y se audita cada ID sin exponer cédula ni nombre del estudiante."""
        prop_propia = self.crear_propuesta(self.estudiante_1, 'PROP-AUD-PROPIA')
        prop_ajena = self.crear_propuesta(self.estudiante_ajeno, 'PROP-AUD-AJENA')

        self._procesar_bloqueado(
            {'accion': 'aprobar', 'propuestas_ids': f'{prop_propia.pk},{prop_ajena.pk}'}
        )

        fila = self._bloqueos('APROBACION_MASIVA_BLOQUEADA').get(id_registro_afectado=prop_ajena.pk)
        self.assertIn('carrera activa del Director', fila.detalle)
        self.assertNotIn(self.estudiante_ajeno.usuario.cedula, fila.detalle)
        self.assertNotIn(self.estudiante_ajeno.usuario.nombre, fila.detalle)
        prop_propia.refresh_from_db()
        self.assertEqual(prop_propia.estado, EstadoTramite.EN_REVISION)

    def test_lote_solo_con_propuestas_ajenas_se_bloquea_en_vez_de_procesar_cero(self):
        """Antes devolvía 0 en silencio; ahora es un intento bloqueado y auditado."""
        prop_ajena = self.crear_propuesta(self.estudiante_ajeno, 'PROP-AUD-SOLO-AJENA')

        self._procesar_bloqueado({'accion': 'aprobar', 'propuestas_ids': f'{prop_ajena.pk}'})

        self.assertEqual(self._bloqueos('APROBACION_MASIVA_BLOQUEADA').count(), 1)

    def test_rechazo_masivo_bloqueado_registra_causal_y_observacion(self):
        """El rechazo masivo bloqueado guarda la causal y la observación del intento."""
        prop1 = self.crear_propuesta(
            self.estudiante_1, 'PROP-AUD-REC-1', estado=EstadoTramite.APROBADO
        )

        self._procesar_bloqueado(
            {
                'accion': 'rechazar',
                'propuestas_ids': f'{prop1.pk}',
                'tipo_rechazo': self.tipo_rechazo_activo.pk,
                'observacion': 'Rechazo en lote no permitido.',
            }
        )

        detalle = self._bloqueos('RECHAZO_MASIVO_BLOQUEADO').get().detalle
        self.assertIn(f'Causal: {self.tipo_rechazo_activo.nombre}', detalle)
        self.assertIn('Rechazo en lote no permitido.', detalle)

    def test_reactivacion_masiva_de_archivada_audita_bloqueo(self):
        """Reactivar en lote una propuesta archivada deja una fila Bloqueado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-AUD-ARCH', estado=EstadoTramite.RECHAZADO
        )
        Propuesta.objects.filter(pk=prop.pk).update(archivada=True, fecha_archivado=timezone.now())

        self._procesar_bloqueado(
            {'accion': 'reactivar', 'propuestas_ids': f'{prop.pk}', 'observacion': 'Reactivar archivada.'}
        )

        fila = self._bloqueos('REACTIVACION_MASIVA_BLOQUEADA').get()
        self.assertEqual(fila.id_registro_afectado, prop.pk)
        self.assertIn('Rechazado -> En revisión', fila.detalle)
        self.assertIn('Reactivar archivada.', fila.detalle)

    def test_reactivacion_masiva_colision_en_lote_audita_cada_propuesta(self):
        """Dos propuestas del mismo estudiante en el lote (RG-05): una fila por propuesta."""
        prop1 = self.crear_propuesta(self.estudiante_1, 'PROP-AUD-DUP-1', estado=EstadoTramite.RECHAZADO)
        prop2 = self.crear_propuesta(self.estudiante_1, 'PROP-AUD-DUP-2', estado=EstadoTramite.RECHAZADO)

        self._procesar_bloqueado(
            {
                'accion': 'reactivar',
                'propuestas_ids': f'{prop1.pk},{prop2.pk}',
                'observacion': 'Reactivar duplicadas.',
            },
            excepcion=ReactivacionInvalidaError,
        )

        filas = self._bloqueos('REACTIVACION_MASIVA_BLOQUEADA')
        self.assertEqual(filas.count(), 2)
        self.assertIn(self.estudiante_1.usuario.nombre, filas.first().detalle)

    def test_reactivacion_masiva_colision_con_bd_conserva_una_fila_con_transicion(self):
        """La colisión RG-05 contra una propuesta activa en BD sigue auditando, ahora con transición."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-AUD-BD-REC', estado=EstadoTramite.RECHAZADO)
        self.crear_propuesta(self.estudiante_1, 'PROP-AUD-BD-ACT')

        self._procesar_bloqueado(
            {'accion': 'reactivar', 'propuestas_ids': f'{prop.pk}', 'observacion': 'Reactivar con colisión.'},
            excepcion=ReactivacionInvalidaError,
        )

        fila = self._bloqueos('REACTIVACION_MASIVA_BLOQUEADA').get()
        self.assertIn('Rechazado -> En revisión', fila.detalle)
        self.assertIn('Reactivar con colisión.', fila.detalle)


class TestSemaforoDetenidoYReactivacion(BaseAprobacionTestCase):
    """El semáforo se detiene al decidir y conserva sus días al reactivar (RG-07)."""

    def _decidir(self, form_cls, prop: Propuesta, hace_dias: int = 0, **datos) -> None:
        """Aplica la decisión y ubica su registro de historial `hace_dias` días atrás."""
        form = form_cls(data={'observacion': 'Observación válida para la decisión.', **datos})
        self.assertTrue(form.is_valid(), form.errors)
        form.procesar(prop, self.user_director)
        HistorialEstado.objects.filter(propuesta=prop).update(
            fecha_hora=timezone.now() - timedelta(days=hace_dias)
        )
        prop.refresh_from_db()

    def _rechazar(self, prop: Propuesta, hace_dias: int) -> None:
        self._decidir(
            RechazoPropuestaForm, prop, hace_dias, tipo_rechazo=self.tipo_rechazo_activo.pk
        )

    def test_rechazo_por_error_y_reactivacion_18_dias_despues_conserva_2_dias(self):
        """Escenario del revisor: 2 días en revisión, rechazo, reactivación 18 días después."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-REV', dias_envio=20)
        self._rechazar(prop, hace_dias=18)

        # Detenido: 18 días después del rechazo sigue marcando los 2 días que estuvo en revisión
        sem = calcular_semaforo(prop)
        self.assertTrue(sem['pausado'])
        self.assertEqual(sem['dias'], 2)

        form = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'Se rechazó por error; el contenido es válido.'}
        )
        self.assertTrue(form.is_valid())
        form.procesar(prop, self.user_director)
        prop.refresh_from_db()

        self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)
        sem = calcular_semaforo(prop)
        self.assertFalse(sem['pausado'])
        self.assertEqual(sem['dias'], 2)
        self.assertEqual(sem['color'], 'verde')

        # Segunda decisión 3 días después: acumula 2 + 3 y vuelve a detenerse
        Propuesta.objects.filter(pk=prop.pk).update(
            fecha_envio=prop.fecha_envio - timedelta(days=3)
        )
        prop.refresh_from_db()
        form = AprobacionPropuestaForm(data={})
        self.assertTrue(form.is_valid())
        form.procesar(prop, self.user_director)
        prop.refresh_from_db()
        sem = calcular_semaforo(prop)
        self.assertTrue(sem['pausado'])
        self.assertEqual(sem['dias'], 5)

    def test_aprobado_y_requiere_modificacion_no_siguen_sumando_dias(self):
        """Tras decidir, los días quedan fijos en los que la propuesta estuvo en revisión."""
        casos = [
            (AprobacionPropuestaForm, self.estudiante_1, EstadoTramite.APROBADO),
            (ModificacionPropuestaForm, self.estudiante_2, EstadoTramite.REQUIERE_MODIFICACION),
        ]
        for form_cls, estudiante, estado in casos:
            with self.subTest(estado=estado):
                prop = self.crear_propuesta(estudiante, f'PROP-SEM-{estado[:3]}', dias_envio=30)
                self._decidir(form_cls, prop, hace_dias=27)
                self.assertEqual(prop.estado, estado)
                sem = calcular_semaforo(prop)
                self.assertTrue(sem['pausado'])
                self.assertEqual(sem['dias'], 3)

    def test_reenvio_desde_requiere_modificacion_no_ajusta_fecha_envio(self):
        """El ajuste de fecha_envio es exclusivo de la reactivación desde 'Rechazado'.

        Al volver a 'En revisión' desde 'Requiere modificación' aplicar_transicion deja
        fecha_envio intacta: reiniciarla al reenviar (semáforo desde 0, RG-03) le
        corresponde a SISTRA-01, no a este módulo.
        """
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-REENV', dias_envio=9)
        self._decidir(ModificacionPropuestaForm, prop, hace_dias=0)
        self.assertEqual(prop.estado, EstadoTramite.REQUIERE_MODIFICACION)
        fecha_envio_antes = prop.fecha_envio

        aplicar_transicion(
            prop, self.user_director, EstadoTramite.EN_REVISION, 'Reenvío', 'REENVIAR_PROPUESTA'
        )
        prop.refresh_from_db()

        self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(prop.fecha_envio, fecha_envio_antes)

    def test_auditoria_de_la_decision_registra_los_dias_en_revision(self):
        """La auditoría guarda los días al decidir, no cero ni los días desde el envío."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-AUD', dias_envio=4)
        self._rechazar(prop, hace_dias=0)
        aud = Auditoria.objects.get(accion='RECHAZAR_PROPUESTA', id_registro_afectado=prop.pk)
        self.assertIn('Días semáforo: 4', aud.detalle)

    def test_reactivacion_masiva_conserva_dias(self):
        """La reactivación masiva retoma cada semáforo con los días que llevaba."""
        prop1 = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-MAS-1', dias_envio=20)
        prop2 = self.crear_propuesta(self.estudiante_2, 'PROP-SEM-MAS-2', dias_envio=30)
        self._rechazar(prop1, hace_dias=18)
        self._rechazar(prop2, hace_dias=21)

        form = AccionMasivaForm(
            data={
                'accion': 'reactivar',
                'propuestas_ids': f'{prop1.pk},{prop2.pk}',
                'observacion': 'Reactivación masiva tras revisar los rechazos.',
            }
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.procesar(self.carrera, self.user_director), 2)

        for prop, dias in [(prop1, 2), (prop2, 9)]:
            prop.refresh_from_db()
            sem = calcular_semaforo(prop)
            self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)
            self.assertEqual(sem['dias'], dias)

    def test_bandeja_muestra_dias_detenidos_sin_consultas_por_fila(self):
        """La bandeja usa la fecha anotada: mismas consultas con 1 o 3 propuestas detenidas."""
        self.client.force_login(self.user_director)
        url = reverse('propuestas:aprobacion')

        def consultas_bandeja() -> tuple[int, dict]:
            self.client.get(url)  # calienta cachés (sesión, permisos)
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            dias = {
                m['propuesta'].codigo: m['semaforo']['dias']
                for m in response.context['propuestas_con_meta']
            }
            return len(ctx), dias

        prop = self.crear_propuesta(self.estudiante_1, 'PROP-SEM-NQ-1', dias_envio=20)
        self._rechazar(prop, hace_dias=18)
        con_una, dias = consultas_bandeja()
        self.assertEqual(dias, {'PROP-SEM-NQ-1': 2})

        for codigo, estudiante in [('PROP-SEM-NQ-2', self.estudiante_1), ('PROP-SEM-NQ-3', self.estudiante_2)]:
            otra = self.crear_propuesta(estudiante, codigo, dias_envio=20)
            self._rechazar(otra, hace_dias=18)
        con_tres, dias = consultas_bandeja()
        self.assertEqual(set(dias.values()), {2})
        self.assertEqual(len(dias), 3)
        self.assertEqual(con_tres, con_una)


# ==============================================================================
# 8. Pruebas de Vistas Web y API Lazy JSON
# ==============================================================================
class TestVistasAprobacion(BaseAprobacionTestCase):
    """Pruebas de endpoints HTTP, autenticación, control de acceso y respuestas JSON."""

    def _assert_un_intento_bloqueado(
        self, prop: Propuesta, motivo: str = '', accion: str = 'CAMBIAR_ESTADO_BLOQUEADO'
    ) -> Auditoria:
        """Verifica que el intento dejó exactamente una fila Bloqueado en auditoría (BRD §5.3.1)."""
        audits = Auditoria.objects.filter(id_registro_afectado=prop.pk)
        self.assertEqual(audits.count(), 1)
        audit = audits.get()
        self.assertEqual(audit.resultado, RESULTADO_BLOQUEADO)
        self.assertEqual(audit.usuario, self.user_director)
        self.assertEqual(audit.accion, accion)
        self.assertIn(prop.proceso.estudiante_carrera.estudiante.usuario.cedula, audit.detalle)
        self.assertIn(f'Transición: {prop.estado} -> ', audit.detalle)
        self.assertIn(motivo, audit.detalle)
        return audit

    def test_bandeja_requiere_login(self):
        """La bandeja redirige al login si el usuario no está autenticado."""
        url = reverse('propuestas:aprobacion')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_bandeja_director_sin_carrera_activa_recibe_403(self):
        """Un Director sin asignación de carrera activa no puede entrar a la bandeja (403)."""
        self.asignacion_director.activo = False
        self.asignacion_director.save()

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:aprobacion'))
        self.assertEqual(response.status_code, 403)

    def test_bandeja_estudiante_autenticado_recibe_403(self):
        """Un estudiante autenticado no puede entrar a la bandeja del Director (403)."""
        self.client.force_login(self.estudiante_1.usuario)
        response = self.client.get(reverse('propuestas:aprobacion'))
        self.assertEqual(response.status_code, 403)

    def test_bandeja_excluye_borradores_y_propuestas_de_otra_carrera(self):
        """La bandeja solo lista propuestas en trámite de la carrera activa (RN-02-01)."""
        prop_revision = self.crear_propuesta(self.estudiante_1, 'PROP-VISTA-REV')
        prop_borrador = self.crear_propuesta(
            self.estudiante_2, 'PROP-VISTA-BORR', estado=EstadoTramite.BORRADOR
        )
        prop_otra = self.crear_propuesta(self.estudiante_ajeno, 'PROP-VISTA-OTRA')

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:aprobacion'))
        self.assertEqual(response.status_code, 200)

        propuestas_mostradas = [
            m['propuesta'].pk for m in response.context['propuestas_con_meta']
        ]
        self.assertIn(prop_revision.pk, propuestas_mostradas)
        self.assertNotIn(prop_borrador.pk, propuestas_mostradas)
        self.assertNotIn(prop_otra.pk, propuestas_mostradas)

    def test_bandeja_bloquea_control_en_estados_sin_decision_del_director(self):
        """Subido en UP, Aprobado en UP y Requiere modificación muestran el control bloqueado.

        El servidor ya rechaza el cambio; la fila no debe ofrecer un control activo que
        solo falla al confirmar. El motivo llega a la plantilla para el aviso.
        """
        estudiante_3 = self._crear_estudiante('1098111004', 'Estudiante Tres', self.carrera)
        props = {
            EstadoTramite.SUBIDO_EN_UP: self.crear_propuesta(
                self.estudiante_1, 'PROP-BLQ-SUB', estado=EstadoTramite.SUBIDO_EN_UP
            ),
            EstadoTramite.APROBADO_EN_UP: self.crear_propuesta(
                self.estudiante_2, 'PROP-BLQ-APUP', estado=EstadoTramite.APROBADO_EN_UP
            ),
            EstadoTramite.REQUIERE_MODIFICACION: self.crear_propuesta(
                estudiante_3, 'PROP-BLQ-MOD', estado=EstadoTramite.REQUIERE_MODIFICACION
            ),
        }

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:aprobacion'))
        metas = {m['propuesta'].pk: m for m in response.context['propuestas_con_meta']}
        html = response.content.decode('utf-8')

        for estado, prop in props.items():
            with self.subTest(estado=estado):
                meta = metas[prop.pk]
                self.assertTrue(meta['bloqueada_reversion'])
                self.assertTrue(meta['motivo_bloqueo'])
                self.assertNotIn(f'aria-label="Cambiar estado {prop.codigo}"', html)

        self.assertEqual(metas[props[EstadoTramite.SUBIDO_EN_UP].pk]['motivo_bloqueo'], MSG_02_07)
        self.assertIn(f'data-motivo="{MSG_02_07}"', html)

    def test_bandeja_mantiene_control_activo_en_revision_y_aprobado_sin_cargue(self):
        """En revisión y Aprobado sin cargue ni informe conservan el control deslizante activo."""
        prop_rev = self.crear_propuesta(self.estudiante_1, 'PROP-ACT-REV')
        prop_apr = self.crear_propuesta(
            self.estudiante_2, 'PROP-ACT-APR', estado=EstadoTramite.APROBADO
        )

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:aprobacion'))
        metas = {m['propuesta'].pk: m for m in response.context['propuestas_con_meta']}
        html = response.content.decode('utf-8')

        for prop in (prop_rev, prop_apr):
            with self.subTest(codigo=prop.codigo):
                self.assertFalse(metas[prop.pk]['bloqueada_reversion'])
                self.assertIn(f'aria-label="Cambiar estado {prop.codigo}"', html)

    def test_bandeja_filtros_busqueda_y_estado(self):
        """Filtra propuestas por texto general (título/código/estudiante) y por estado."""
        p1 = self.crear_propuesta(
            self.estudiante_1, 'PROP-ALFA-01', titulo='Sistema de Riego Comunitario'
        )
        p2 = self.crear_propuesta(
            self.estudiante_2, 'PROP-BETA-02', titulo='Capacitación a Tercera Edad'
        )

        self.client.force_login(self.user_director)

        # Búsqueda por texto que coincide con p1
        resp_busq = self.client.get(reverse('propuestas:aprobacion'), {'buscar': 'Riego'})
        pks_busq = [m['propuesta'].pk for m in resp_busq.context['propuestas_con_meta']]
        self.assertIn(p1.pk, pks_busq)
        self.assertNotIn(p2.pk, pks_busq)

        # Filtro por estado
        p2.estado = EstadoTramite.APROBADO
        p2.save()
        resp_est = self.client.get(
            reverse('propuestas:aprobacion'), {'estado': EstadoTramite.APROBADO}
        )
        pks_est = [m['propuesta'].pk for m in resp_est.context['propuestas_con_meta']]
        self.assertIn(p2.pk, pks_est)
        self.assertNotIn(p1.pk, pks_est)

    def test_cambiar_estado_post_aprobar_exito(self):
        """Endpoint POST para aplicar decisión de aprobación individual."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-POST-APR')
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(
            url,
            {'nuevo_estado': EstadoTramite.APROBADO, 'observacion': 'Aprobada por endpoint web.'},
        )
        self.assertEqual(response.status_code, 302)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)

    def test_bandeja_incluye_visor_real_del_pdf_y_avisos_de_procesando(self):
        """El detalle trae el visor real del PDF (sin la hoja simulada ni 'Pág. 1 / 1' fijo)
        con su carga y reintento, y cada ventana de confirmación su aviso de procesando."""
        self.client.force_login(self.user_director)
        html = self.client.get(reverse('propuestas:aprobacion')).content.decode('utf-8')

        self.assertIn('id="det-doc-iframe"', html)
        self.assertIn('Cargando documento PDF...', html)
        self.assertIn('id="det-doc-reintentar"', html)
        self.assertNotIn('det-doc-hoja', html)
        self.assertNotIn('Pág. 1 / 1', html)
        self.assertEqual(html.count('data-procesando style="display: none;"'), 3)

    def test_paginacion_conserva_busqueda_con_caracteres_especiales(self):
        """Los enlaces de página codifican la búsqueda: 'Peña & Cía' no se corta en el '&'."""
        for i in range(ELEMENTOS_POR_PAGINA + 1):
            estudiante = self._crear_estudiante(f'10985000{i:02d}', f'Estudiante Página {i}', self.carrera)
            self.crear_propuesta(estudiante, f'PROP-PAG-{i:02d}', titulo=f'Proyecto Peña & Cía {i}')
        self.client.force_login(self.user_director)

        response = self.client.get(reverse('propuestas:aprobacion'), {'buscar': 'Peña & Cía'})
        html = response.content.decode('utf-8')

        self.assertEqual(response.context['total_propuestas'], ELEMENTOS_POR_PAGINA + 1)
        self.assertIn('buscar=Pe%C3%B1a%20%26%20C%C3%ADa', html)
        siguiente = self.client.get(
            reverse('propuestas:aprobacion'), {'page': 2, 'buscar': 'Peña & Cía'}
        )
        self.assertEqual(len(siguiente.context['propuestas_con_meta']), 1)

    def test_bandeja_busqueda_en_tiempo_real_y_carga_de_tabla(self):
        """La búsqueda se envía sola al dejar de escribir (TXT-BUSQ-GEN) y la tabla tiene su indicador de carga."""
        self.client.force_login(self.user_director)
        html = self.client.get(reverse('propuestas:aprobacion')).content.decode('utf-8')

        self.assertIn('ESPERA_BUSQUEDA_MS', html)
        self.assertIn('id="tbl-cargando"', html)

    def test_bandeja_usa_msg_02_05_para_campos_obligatorios(self):
        """El aviso de campos vacíos de las ventanas es MSG-02-05 y sale de la constante de Python."""
        self.client.force_login(self.user_director)
        html = self.client.get(reverse('propuestas:aprobacion')).content.decode('utf-8')

        self.assertIn(f"const MSG_02_05 = '{MSG_02_05}';", html)

    def test_bandeja_vacia_muestra_mensaje_del_brd_sin_filtros(self):
        """Sin propuestas ni filtros se muestra el estado vacío del BRD, sin 'Restablecer filtros'."""
        self.client.force_login(self.user_director)
        html = self.client.get(reverse('propuestas:aprobacion')).content.decode('utf-8')

        self.assertIn('No tienes propuestas para revisar.', html)
        self.assertNotIn('Restablecer filtros', html)

    def test_bandeja_vacia_con_filtros_ofrece_restablecerlos(self):
        """Si los filtros no encuentran nada se explica y se ofrece restablecerlos."""
        self.crear_propuesta(self.estudiante_1, 'PROP-VACIA-FILTRO')
        self.client.force_login(self.user_director)
        html = self.client.get(
            reverse('propuestas:aprobacion'), {'buscar': 'texto-que-no-existe'}
        ).content.decode('utf-8')

        self.assertIn('que coincidan con los criterios seleccionados', html)
        self.assertIn('Restablecer filtros', html)
        self.assertNotIn('No tienes propuestas para revisar.', html)

    def test_errores_inesperados_se_registran_sin_exponer_detalles(self):
        """BRD §5.3.5: las operaciones fallidas se registran (log + auditoría Fallo) y el
        Director solo ve un mensaje general, sin el detalle técnico."""
        from unittest import mock

        prop = self.crear_propuesta(self.estudiante_1, 'PROP-FALLO-1')
        rechazada = self.crear_propuesta(
            self.estudiante_2, 'PROP-FALLO-2', estado=EstadoTramite.RECHAZADO
        )
        self.client.force_login(self.user_director)
        casos = [
            (
                AprobacionPropuestaForm,
                reverse('propuestas:cambiar_estado', args=[prop.pk]),
                {'nuevo_estado': EstadoTramite.APROBADO},
                prop.pk,
            ),
            (
                ReactivacionPropuestaForm,
                reverse('propuestas:reactivar_propuesta', args=[rechazada.pk]),
                {'motivo_reactivacion': 'Reactivación que falla en el servidor.'},
                rechazada.pk,
            ),
            (
                AccionMasivaForm,
                reverse('propuestas:accion_masiva'),
                {'accion': 'aprobar', 'propuestas_ids': f'{prop.pk}'},
                None,
            ),
        ]
        for form_cls, url, datos, id_registro in casos:
            with self.subTest(form=form_cls.__name__):
                with mock.patch.object(form_cls, 'procesar', side_effect=RuntimeError('detalle-tecnico-secreto')), \
                        self.assertLogs('apps.propuestas.views.aprobacion', level='ERROR') as logs:
                    response = self.client.post(url, datos, follow=True)

                mensajes = ' '.join(str(m) for m in response.context['messages'])
                self.assertIn('No fue posible', mensajes)
                self.assertNotIn('detalle-tecnico-secreto', mensajes)
                self.assertIn('detalle-tecnico-secreto', '\n'.join(logs.output))

                fila = Auditoria.objects.filter(resultado='Fallo').latest('id_auditoria')
                self.assertEqual(fila.usuario_id, self.user_director.pk)
                self.assertEqual(fila.id_registro_afectado, id_registro)
                self.assertNotIn('detalle-tecnico-secreto', fila.detalle)

    def test_acciones_post_sin_carrera_activa_responden_403(self):
        """Decidir, reactivar y la acción masiva niegan el acceso (403) sin carrera activa, sin cambios."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-403-DEC')
        rechazada = self.crear_propuesta(
            self.estudiante_2, 'PROP-403-REA', estado=EstadoTramite.RECHAZADO
        )
        self.asignacion_director.activo = False
        self.asignacion_director.save()
        self.client.force_login(self.user_director)

        casos = [
            (
                reverse('propuestas:cambiar_estado', args=[prop.pk]),
                {'nuevo_estado': EstadoTramite.APROBADO},
            ),
            (
                reverse('propuestas:reactivar_propuesta', args=[rechazada.pk]),
                {'motivo_reactivacion': 'Reactivación sin carrera activa.'},
            ),
            (
                reverse('propuestas:accion_masiva'),
                {'accion': 'aprobar', 'propuestas_ids': f'{prop.pk}'},
            ),
        ]
        for url, datos in casos:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, datos).status_code, 403)

        prop.refresh_from_db()
        rechazada.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(rechazada.estado, EstadoTramite.RECHAZADO)

    def test_errores_de_formulario_se_muestran_como_texto_plano(self):
        """Los errores del formulario llegan al Director como texto, sin <ul> ni corchetes."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-MSG-TXT')
        rechazada = self.crear_propuesta(
            self.estudiante_2, 'PROP-MSG-REA', estado=EstadoTramite.RECHAZADO
        )
        self.client.force_login(self.user_director)

        casos = [
            (
                reverse('propuestas:cambiar_estado', args=[prop.pk]),
                {'nuevo_estado': EstadoTramite.REQUIERE_MODIFICACION, 'observacion': 'corto'},
            ),
            (
                reverse('propuestas:reactivar_propuesta', args=[rechazada.pk]),
                {'motivo_reactivacion': 'corto'},
            ),
            (reverse('propuestas:accion_masiva'), {'accion': 'aprobar', 'propuestas_ids': ''}),
        ]
        for url, datos in casos:
            with self.subTest(url=url):
                response = self.client.post(url, datos, follow=True)
                mensajes = [str(m) for m in response.context['messages']]
                self.assertTrue(mensajes)
                for texto in mensajes:
                    self.assertNotIn('<', texto)
                    self.assertFalse(texto.startswith('['))

    def test_cambiar_estado_post_modificar_exito(self):
        """Endpoint POST para solicitar correcciones individuales."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-POST-MOD')
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(
            url,
            {
                'nuevo_estado': EstadoTramite.REQUIERE_MODIFICACION,
                'observacion': 'Corregir el capítulo segundo y ajustar el presupuesto.',
            },
        )
        self.assertEqual(response.status_code, 302)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.REQUIERE_MODIFICACION)

    def test_cambiar_estado_post_rechazar_exito(self):
        """Endpoint POST para rechazar propuesta individual."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-POST-REC')
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(
            url,
            {
                'nuevo_estado': EstadoTramite.RECHAZADO,
                'tipo_rechazo': self.tipo_rechazo_activo.pk,
                'observacion': 'Rechazada formalmente por el Director de carrera.',
            },
        )
        self.assertEqual(response.status_code, 302)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.RECHAZADO)

    def test_cambiar_estado_post_bloqueado_desde_rechazado_sin_modal(self):
        """Bloquea cualquier cambio desde Rechazado a través del endpoint de slider (P-2)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-POST-BLOQ-REC', estado=EstadoTramite.RECHAZADO
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(url, {'nuevo_estado': EstadoTramite.APROBADO})
        self.assertEqual(response.status_code, 302)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.RECHAZADO)
        self._assert_un_intento_bloqueado(prop, 'solo puede ser reactivada')

    def test_cambiar_estado_post_bloqueado_desde_borrador(self):
        """Bloquea cambiar estado si la propuesta se encuentra en BORRADOR."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-BLOQ-BORR', estado=EstadoTramite.BORRADOR
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(url, {'nuevo_estado': EstadoTramite.APROBADO})
        self.assertEqual(response.status_code, 302)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.BORRADOR)
        self._assert_un_intento_bloqueado(prop, 'estado actual: Borrador')

    def test_cambiar_estado_post_bloqueado_desde_requiere_modificacion(self):
        """Bloquea cambiar estado si la propuesta se encuentra en REQUIERE_MODIFICACION."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-BLOQ-MOD', estado=EstadoTramite.REQUIERE_MODIFICACION
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(url, {'nuevo_estado': EstadoTramite.APROBADO})
        self.assertEqual(response.status_code, 302)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.REQUIERE_MODIFICACION)
        self._assert_un_intento_bloqueado(prop, 'estado actual: Requiere modificación')

    def test_cambiar_estado_post_bloqueado_desde_aprobado_si_tiene_cargue_up(self):
        """Bloquea cambiar estado desde APROBADO si ya tiene cargue UP registrado (RN-02-04)."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-BLOQ-CARGUE', estado=EstadoTramite.APROBADO
        )
        CargueUp.objects.create(
            propuesta=prop,
            estado_verificacion=EstadoVerificacion.PENDIENTE,
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(
            url,
            {
                'nuevo_estado': EstadoTramite.REQUIERE_MODIFICACION,
                'observacion': 'Ajuste posterior al cargue oficial',
            },
        )
        self.assertEqual(response.status_code, 302)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)
        audit = self._assert_un_intento_bloqueado(prop, MSG_02_07)
        self.assertIn('Ajuste posterior al cargue oficial', audit.detalle)

    def test_cambiar_estado_post_rechazo_bloqueado_desde_aprobado_audita_causal(self):
        """Rechazar un Aprobado con cargue en UP se bloquea y audita una sola vez con la causal."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-BLOQ-CARGUE-REC', estado=EstadoTramite.APROBADO
        )
        CargueUp.objects.create(
            propuesta=prop,
            estado_verificacion=EstadoVerificacion.PENDIENTE,
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        response = self.client.post(
            url,
            {
                'nuevo_estado': EstadoTramite.RECHAZADO,
                'tipo_rechazo': self.tipo_rechazo_activo.pk,
                'observacion': 'x' * 5000,
            },
        )
        self.assertEqual(response.status_code, 302)

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)
        audit = self._assert_un_intento_bloqueado(prop, MSG_02_07)
        self.assertIn(f'-> {EstadoTramite.RECHAZADO}', audit.detalle)
        self.assertIn(f'Causal: {self.tipo_rechazo_activo.nombre}', audit.detalle)
        # La observación del POST crudo se recorta antes de guardarse.
        self.assertIn('x' * 1000, audit.detalle)
        self.assertNotIn('x' * 1001, audit.detalle)

    def test_cambiar_estado_post_desde_aprobado_sin_bloqueo_no_audita_bloqueo(self):
        """Revertir un Aprobado sin cargue ni informe sigue permitido y no deja fila Bloqueado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-APR-LIBRE', estado=EstadoTramite.APROBADO
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:cambiar_estado', args=[prop.pk])
        self.client.post(
            url,
            {
                'nuevo_estado': EstadoTramite.REQUIERE_MODIFICACION,
                'observacion': 'Ajustar el cronograma propuesto',
            },
        )

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.REQUIERE_MODIFICACION)
        self.assertFalse(
            Auditoria.objects.filter(
                id_registro_afectado=prop.pk, resultado=RESULTADO_BLOQUEADO
            ).exists()
        )

    def test_bandeja_filtro_semaforo_limites_dinamicos_desde_bd(self):
        """El filtrado por semáforo en bandeja obedece los límites dinámicos de Parametro."""
        Parametro.objects.create(
            clave='dias_semaforo_verde',
            valor='3',
            usuario_actualizacion=self.user_director,
        )
        Parametro.objects.create(
            clave='dias_semaforo_amarillo',
            valor='8',
            usuario_actualizacion=self.user_director,
        )
        p_verde = self.crear_propuesta(self.estudiante_1, 'P-FILT-VERDE', dias_envio=2)
        p_amarillo = self.crear_propuesta(self.estudiante_2, 'P-FILT-AMAR', dias_envio=5)

        self.client.force_login(self.user_director)
        response_verde = self.client.get(reverse('propuestas:aprobacion'), {'semaforo': 'verde'})
        self.assertEqual(response_verde.status_code, 200)
        props_verde = [m['propuesta'].pk for m in response_verde.context['propuestas_con_meta']]
        self.assertIn(p_verde.pk, props_verde)
        self.assertNotIn(p_amarillo.pk, props_verde)

        response_amarillo = self.client.get(reverse('propuestas:aprobacion'), {'semaforo': 'amarillo'})
        self.assertEqual(response_amarillo.status_code, 200)
        props_amarillo = [m['propuesta'].pk for m in response_amarillo.context['propuestas_con_meta']]
        self.assertIn(p_amarillo.pk, props_amarillo)
        self.assertNotIn(p_verde.pk, props_amarillo)

    def test_bandeja_filtro_semaforo_coincide_con_el_color_de_la_fila_en_los_bordes(self):
        """Cada propuesta aparece solo en el filtro del color que muestra su fila.

        La fila cuenta días completos (7,5 días = 7 → verde); el filtro debe cortar igual.
        """
        estudiante_3 = self._crear_estudiante('1098111005', 'Estudiante Cinco', self.carrera)
        props = [
            self.crear_propuesta(self.estudiante_1, 'P-BORDE-7.5', dias_envio=7.5),
            self.crear_propuesta(self.estudiante_2, 'P-BORDE-14.5', dias_envio=14.5),
            self.crear_propuesta(estudiante_3, 'P-BORDE-15', dias_envio=15),
        ]
        self.client.force_login(self.user_director)
        todas = self.client.get(reverse('propuestas:aprobacion')).context['propuestas_con_meta']
        color_fila = {m['propuesta'].pk: m['semaforo']['color'] for m in todas}
        self.assertEqual(
            [color_fila[p.pk] for p in props], ['verde', 'amarillo', 'rojo']
        )

        for color in ('verde', 'amarillo', 'rojo'):
            with self.subTest(filtro=color):
                filtradas = self.client.get(
                    reverse('propuestas:aprobacion'), {'semaforo': color}
                ).context['propuestas_con_meta']
                self.assertEqual(
                    {m['propuesta'].pk for m in filtradas},
                    {pk for pk, c in color_fila.items() if c == color},
                )

    def test_reactivar_propuesta_post_exito(self):
        """Endpoint POST para reactivar una propuesta rechazada por error."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-POST-REA', estado=EstadoTramite.RECHAZADO
        )
        self.client.force_login(self.user_director)

        url = reverse('propuestas:reactivar_propuesta', args=[prop.pk])
        response = self.client.post(
            url,
            {
                'motivo_reactivacion': 'Reactivada tras solicitud formal y comprobación de error.',
            },
        )
        self.assertEqual(response.status_code, 302)
        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)

    def _post_reactivar(self, prop: Propuesta, motivo: str) -> list[str]:
        """Envía la reactivación como Director y devuelve los mensajes mostrados."""
        self.client.force_login(self.user_director)
        url = reverse('propuestas:reactivar_propuesta', args=[prop.pk])
        response = self.client.post(url, {'motivo_reactivacion': motivo}, follow=True)
        return [str(m) for m in response.context['messages']]

    def test_reactivar_propuesta_post_bloqueado_si_no_esta_rechazada(self):
        """Reactivar una propuesta no Rechazada muestra error (no éxito) y audita un Bloqueado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-POST-REA-NOREC', estado=EstadoTramite.APROBADO
        )
        mensajes = self._post_reactivar(prop, 'Intento de reactivar una aprobada.')

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.APROBADO)
        self.assertNotIn(MSG_02_04, mensajes)
        self.assertTrue(any('estado actual: Aprobado' in m for m in mensajes))
        audit = self._assert_un_intento_bloqueado(
            prop, 'estado actual: Aprobado', accion='REACTIVAR_PROPUESTA_BLOQUEADA'
        )
        self.assertIn(f'-> {EstadoTramite.EN_REVISION}', audit.detalle)
        self.assertIn('Intento de reactivar una aprobada.', audit.detalle)

    def test_reactivar_propuesta_post_bloqueado_si_esta_archivada(self):
        """Reactivar una propuesta archivada se bloquea y audita un único Bloqueado con el motivo."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-POST-REA-ARCH', estado=EstadoTramite.RECHAZADO, archivada=True
        )
        mensajes = self._post_reactivar(prop, 'Intento de reactivar una archivada.')

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.RECHAZADO)
        self.assertNotIn(MSG_02_04, mensajes)
        self._assert_un_intento_bloqueado(
            prop, 'archivada', accion='REACTIVAR_PROPUESTA_BLOQUEADA'
        )

    def test_reactivar_propuesta_post_bloqueado_rg05_audita_una_sola_vez(self):
        """La colisión RG-05 vía vista deja exactamente una fila Bloqueado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-POST-REA-COL1', estado=EstadoTramite.RECHAZADO
        )
        self.crear_propuesta(self.estudiante_1, 'PROP-POST-REA-COL2', estado=EstadoTramite.EN_REVISION)
        mensajes = self._post_reactivar(prop, 'Intento con otra propuesta activa.')

        prop.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.RECHAZADO)
        self.assertNotIn(MSG_02_04, mensajes)
        self._assert_un_intento_bloqueado(
            prop, self.estudiante_1.usuario.nombre, accion='REACTIVAR_PROPUESTA_BLOQUEADA'
        )

    def test_reactivar_propuesta_post_motivo_invalido_no_audita(self):
        """Un motivo demasiado corto es error de validación, no intento bloqueado."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-POST-REA-CORTO', estado=EstadoTramite.APROBADO
        )
        self._post_reactivar(prop, 'corto')
        self.assertFalse(Auditoria.objects.filter(id_registro_afectado=prop.pk).exists())

    def test_accion_masiva_post_exito(self):
        """Endpoint POST de acciones masivas procesa el lote."""
        p1 = self.crear_propuesta(self.estudiante_1, 'PROP-MAS-POST-1')
        p2 = self.crear_propuesta(self.estudiante_2, 'PROP-MAS-POST-2')
        self.client.force_login(self.user_director)

        url = reverse('propuestas:accion_masiva')
        response = self.client.post(
            url,
            {
                'accion': 'aprobar',
                'propuestas_ids': f'{p1.pk},{p2.pk}',
                'observacion': 'Aprobación en lote desde la web.',
            },
        )
        self.assertEqual(response.status_code, 302)
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.estado, EstadoTramite.APROBADO)
        self.assertEqual(p2.estado, EstadoTramite.APROBADO)

    def test_accion_masiva_post_estados_mixtos_muestra_mensaje_sin_corchetes(self):
        """El error de validación del lote se muestra como texto, no como lista ['...']."""
        p1 = self.crear_propuesta(self.estudiante_1, 'PROP-MAS-MIX-1')
        p2 = self.crear_propuesta(
            self.estudiante_2, 'PROP-MAS-MIX-2', estado=EstadoTramite.APROBADO
        )
        self.client.force_login(self.user_director)

        response = self.client.post(
            reverse('propuestas:accion_masiva'),
            {'accion': 'aprobar', 'propuestas_ids': f'{p1.pk},{p2.pk}'},
            follow=True,
        )
        mensajes = [str(m) for m in response.context['messages']]

        self.assertEqual(
            mensajes,
            ["Para aprobar o rechazar de forma masiva, todas las propuestas deben estar exclusivamente en estado 'En revisión'."],
        )
        p1.refresh_from_db()
        self.assertEqual(p1.estado, EstadoTramite.EN_REVISION)

    def test_detalle_propuesta_lazy_json(self):
        """Endpoint JSON lazy de detalle responde estructura completa (SISTRA-01 + historial)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-JSON-DET', dias_envio=3)
        ActividadCronograma.objects.create(
            propuesta=prop,
            nombre='Taller Comunitario',
            descripcion='Taller inicial',
            fecha_inicio=timezone.localdate(),
            fecha_fin=timezone.localdate() + timedelta(days=10),
            orden=1,
            responsable='Estudiante 1',
        )

        self.client.force_login(self.user_director)
        url = reverse('propuestas:detalle_propuesta', args=[prop.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        datos = response.json()
        self.assertEqual(datos['id_propuesta'], prop.pk)
        self.assertEqual(datos['codigo'], prop.codigo)
        self.assertEqual(datos['titulo'], prop.titulo)
        self.assertEqual(datos['programa'], self.carrera.nombre)
        self.assertEqual(datos['estudiante']['nombre'], self.estudiante_1.usuario.nombre)
        self.assertEqual(datos['estudiante']['programa'], self.carrera.nombre)
        self.assertEqual(datos['semaforo']['color'], 'verde')
        self.assertTrue(datos['puede_revertir'])
        self.assertEqual(len(datos['cronograma']), 1)
        self.assertEqual(datos['cronograma'][0]['nombre'], 'Taller Comunitario')

    def test_descargar_documento_404_si_no_existe_archivo_ex06(self):
        """Descarga de documento responde 404 seguro si no hay archivo (EX-06)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-DOC-404')
        self.client.force_login(self.user_director)

        url = reverse('propuestas:descargar_documento', args=[prop.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def _media_root_temporal(self) -> Path:
        """Apunta MEDIA_ROOT a un directorio temporal que se borra al terminar la prueba."""
        directorio = tempfile.TemporaryDirectory()
        self.addCleanup(directorio.cleanup)
        ajuste = override_settings(MEDIA_ROOT=directorio.name)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        return Path(directorio.name)

    def _propuesta_con_documento(self, codigo: str, ruta_archivo: str, nombre_archivo: str) -> Propuesta:
        """Crea una propuesta cuya versión de plantilla apunta a la ruta indicada."""
        from apps.parametrizacion.models import Plantilla, VersionPlantilla

        plantilla = Plantilla.objects.create(nombre=f'Plantilla {codigo}', tipo='propuesta', estado='activo')
        version = VersionPlantilla.objects.create(
            plantilla=plantilla,
            usuario=self.user_director,
            numero_version=1,
            nombre_archivo=nombre_archivo,
            ruta_archivo=ruta_archivo,
            es_vigente=True,
        )
        prop = self.crear_propuesta(self.estudiante_1, codigo)
        prop.version_plantilla = version
        prop.save()
        return prop

    def test_descargar_documento_pdf_content_type_inline(self):
        """Descarga de documento PDF responde content_type application/pdf e inline para previsualización."""
        media = self._media_root_temporal()
        (media / 'propuesta.pdf').write_bytes(b'%PDF-1.4 dummy content')
        prop = self._propuesta_con_documento(
            'PROP-DOC-PDF', str(media / 'propuesta.pdf'), 'propuesta_estudiante.pdf'
        )

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:descargar_documento', args=[prop.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            response['Content-Disposition'], 'inline; filename="propuesta_estudiante.pdf"'
        )
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 dummy content')

    def test_descargar_documento_fuera_de_media_root_responde_404(self):
        """Una ruta guardada que cae fuera de MEDIA_ROOT (absoluta o con '../') nunca se sirve."""
        media = self._media_root_temporal()
        externo = tempfile.TemporaryDirectory()
        self.addCleanup(externo.cleanup)
        secreto = Path(externo.name) / 'secreto.pdf'
        secreto.write_bytes(b'%PDF-1.4 secreto')
        relativa = Path('..') / secreto.relative_to(media.parent)
        # Sanidad: ambas rutas apuntan a un archivo que sí existe.
        self.assertTrue((media / relativa).is_file())

        prop = self._propuesta_con_documento('PROP-DOC-FUERA', str(secreto), 'secreto.pdf')
        self.client.force_login(self.user_director)
        for ruta in (str(secreto), str(relativa)):
            with self.subTest(ruta=ruta):
                prop.version_plantilla.ruta_archivo = ruta
                prop.version_plantilla.save()
                response = self.client.get(reverse('propuestas:descargar_documento', args=[prop.pk]))
                self.assertEqual(response.status_code, 404)

    def test_descargar_documento_nombre_con_comillas_no_rompe_encabezado(self):
        """Un nombre de archivo con comillas dobles llega escapado en Content-Disposition."""
        media = self._media_root_temporal()
        (media / 'propuesta.pdf').write_bytes(b'%PDF-1.4 dummy content')
        # Ruta relativa a MEDIA_ROOT: también debe resolverse.
        prop = self._propuesta_con_documento('PROP-DOC-COMILLAS', 'propuesta.pdf', 'propuesta "final".pdf')

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:descargar_documento', args=[prop.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(
            response['Content-Disposition'], 'inline; filename="propuesta \\"final\\".pdf"'
        )
        # Consumir el contenido cierra el archivo servido.
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 dummy content')

    def test_descargar_documento_no_pdf_se_sirve_como_adjunto(self):
        """Todo lo que no sea PDF (HTML, SVG, PDF comprimido, sin extensión) baja como adjunto, nunca inline."""
        media = self._media_root_temporal()
        (media / 'archivo.bin').write_bytes(b'<script>alert(1)</script>')
        prop = self._propuesta_con_documento('PROP-DOC-ADJ', 'archivo.bin', 'propuesta.html')

        self.client.force_login(self.user_director)
        for nombre in ('propuesta.html', 'diagrama.svg', 'propuesta.pdf.gz', 'propuesta'):
            with self.subTest(nombre=nombre):
                prop.version_plantilla.nombre_archivo = nombre
                prop.version_plantilla.save()
                response = self.client.get(reverse('propuestas:descargar_documento', args=[prop.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Disposition'], f'attachment; filename="{nombre}"')
                self.assertNotEqual(response['Content-Type'], 'application/pdf')
                # SecurityMiddleware impide que el navegador reinterprete el tipo declarado.
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                # Consumir el contenido cierra el archivo servido.
                self.assertEqual(b''.join(response.streaming_content), b'<script>alert(1)</script>')

    def test_descargar_documento_director_sin_carrera_activa_recibe_403(self):
        """Un Director sin asignación de carrera activa no puede descargar documentos (403)."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-DOC-403')
        self.asignacion_director.activo = False
        self.asignacion_director.save()
        self.client.force_login(self.user_director)

        response = self.client.get(reverse('propuestas:descargar_documento', args=[prop.pk]))
        self.assertEqual(response.status_code, 403)


class TestPermisoAprobacion(BaseAprobacionTestCase):
    """El acceso exige el permiso propuesta.aprobar además de la carrera activa (BRD Tabla 32)."""

    PERMISO = 'propuesta.aprobar'

    def _quitar_permiso_al_director(self):
        RolPermiso.objects.filter(rol=self.rol_director, permiso__nombre=self.PERMISO).delete()

    def test_la_migracion_asigna_el_permiso_solo_al_director(self):
        """Sembrado por migración: lo tiene el Director; ni el Administrador ni el Estudiante."""
        roles = set(
            RolPermiso.objects.filter(permiso__nombre=self.PERMISO).values_list('rol__nombre', flat=True)
        )
        self.assertEqual(roles, {'Director'})
        self.assertTrue(self.user_director.has_perm(self.PERMISO))

    def test_director_sin_permiso_recibe_403_en_todas_las_vistas(self):
        """Si el ADMO le quita el permiso al rol, el Director pierde el acceso aunque tenga carrera."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-PERM-1')
        rechazada = self.crear_propuesta(
            self.estudiante_2, 'PROP-PERM-2', estado=EstadoTramite.RECHAZADO
        )
        self._quitar_permiso_al_director()
        self.client.force_login(self.user_director)

        peticiones = [
            ('get', reverse('propuestas:aprobacion'), {}),
            ('get', reverse('propuestas:detalle_propuesta', args=[prop.pk]), {}),
            ('get', reverse('propuestas:descargar_documento', args=[prop.pk]), {}),
            ('post', reverse('propuestas:cambiar_estado', args=[prop.pk]), {'nuevo_estado': EstadoTramite.APROBADO}),
            (
                'post',
                reverse('propuestas:reactivar_propuesta', args=[rechazada.pk]),
                {'motivo_reactivacion': 'Reactivación sin permiso.'},
            ),
            ('post', reverse('propuestas:accion_masiva'), {'accion': 'aprobar', 'propuestas_ids': f'{prop.pk}'}),
        ]
        for metodo, url, datos in peticiones:
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, metodo)(url, datos).status_code, 403)

        prop.refresh_from_db()
        rechazada.refresh_from_db()
        self.assertEqual(prop.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(rechazada.estado, EstadoTramite.RECHAZADO)

    def test_anonimo_sigue_yendo_al_login(self):
        """Sin sesión no hay 403: se redirige al Logueo (SISTRA-13)."""
        response = self.client.get(reverse('propuestas:aprobacion'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_administrador_no_puede_decidir(self):
        """El ADMO consulta según sus permisos, sin decidir: no tiene propuesta.aprobar."""
        admo = Usuario.objects.create_user(
            correo_institucional='admo@unipamplona.edu.co',
            password='Password123!',
            nombre='Administrador',
            cedula='1098000099',
            nombre_usuario='admo',
            rol=Rol.objects.get(nombre='Administrador'),
            requiere_cambio_contrasena=False,
        )
        self.client.force_login(admo)
        self.assertEqual(self.client.get(reverse('propuestas:aprobacion')).status_code, 403)

    def test_rol_nuevo_con_permiso_y_carrera_activa_puede_entrar(self):
        """No depende del nombre del rol: un rol creado por el ADMO con el permiso y carrera entra."""
        rol = Rol.objects.create(nombre='Coordinador', estado=Estado.ACTIVO)
        RolPermiso.objects.create(rol=rol, permiso=Permiso.objects.get(nombre=self.PERMISO))
        coordinador = Usuario.objects.create_user(
            correo_institucional='coordinador@unipamplona.edu.co',
            password='Password123!',
            nombre='Coordinadora Electrónica',
            cedula='1098000077',
            nombre_usuario='coordinador',
            rol=rol,
            requiere_cambio_contrasena=False,
        )
        DirectorCarrera.objects.create(
            director=Director.objects.create(usuario=coordinador),
            carrera=self.otra_carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )
        prop = self.crear_propuesta(self.estudiante_ajeno, 'PROP-PERM-COORD')

        self.client.force_login(coordinador)
        response = self.client.get(reverse('propuestas:aprobacion'))

        self.assertEqual(response.status_code, 200)
        self.assertIn(prop.pk, [m['propuesta'].pk for m in response.context['propuestas_con_meta']])
