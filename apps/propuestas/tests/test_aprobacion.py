"""SISTRA-02 · Aprobación de propuesta: pruebas automatizadas exhaustivas.

Cubre:
- Dominio y cálculos: sanitización XSS, semáforo (RG-07), reversión de aprobación (RN-02-04 / EX-05).
- Formularios individuales: Aprobación, Modificación, Rechazo y Reactivación.
- Formulario de acciones masivas: AccionMasivaForm (aislamiento, compatibilidad, colisiones RG-05 / EX-02).
- Vistas web y API JSON: bandeja, decisión individual, reactivación, masivo, detalle lazy y descarga.
- Casos desfavorables y de borde: ataques XSS, longitudes límite, duplicados, concurrencia y bloqueos.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
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
    MSG_02_06,
    MSG_02_07,
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
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado, Rol

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

    def test_sanitizar_texto_ataque_xss_y_etiquetas(self):
        """Elimina etiquetas HTML peligrosas sin escapar comillas ni ampersand (Django autoescapa al renderizar)."""
        xss_input = "<script>alert('Ataque XSS')</script>Observación limpia"
        resultado = sanitizar_texto(xss_input)
        self.assertNotIn('<script>', resultado)
        self.assertNotIn('</script>', resultado)
        self.assertEqual(resultado, "alert('Ataque XSS')Observación limpia")

        html_input = "<b>Negrita</b> & <img src=x onerror=alert(1)>Texto final"
        resultado_html = sanitizar_texto(html_input)
        self.assertNotIn('<b>', resultado_html)
        self.assertNotIn('<img', resultado_html)
        self.assertEqual(resultado_html, "Negrita & Texto final")

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
        """Sanitiza el texto de búsqueda y valida opciones de los selectores."""
        data = {
            'buscar': "<script>alert(1)</script> Juan Pérez ",
            'estado': EstadoTramite.EN_REVISION,
            'semaforo': 'amarillo',
        }
        form = FiltroBandejaPropuestasForm(data=data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['buscar'], 'alert(1) Juan Pérez')
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
        """Aprueba con éxito registrando la observación opcional sanitizada."""
        prop = self.crear_propuesta(self.estudiante_1, 'PROP-APR-2')
        obs = '<b>Felicitaciones</b>, propuesta excelente para la comunidad.'
        form = AprobacionPropuestaForm(data={'observacion': obs})
        self.assertTrue(form.is_valid())

        form.procesar(prop, self.user_director)
        hist = HistorialEstado.objects.filter(propuesta=prop).latest('id_historial')
        self.assertEqual(hist.observacion, 'Felicitaciones, propuesta excelente para la comunidad.')

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

        # Semáforo se reactiva y cuenta desde fecha_envio original
        sem = calcular_semaforo(prop)
        self.assertFalse(sem['pausado'])
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
        audit = Auditoria.objects.filter(
            id_registro_afectado=prop_rechazada.pk, accion='REACTIVAR_PROPUESTA_BLOQUEADA'
        ).latest('id_auditoria')
        self.assertEqual(audit.resultado, 'Bloqueado')

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

    def test_reactivar_ignora_propuestas_que_no_estan_en_rechazado(self):
        """Si la propuesta no está en Rechazado, no ejecuta cambios."""
        prop = self.crear_propuesta(
            self.estudiante_1, 'PROP-REA-IGN', estado=EstadoTramite.EN_REVISION
        )
        total_hist_antes = HistorialEstado.objects.filter(propuesta=prop).count()
        form = ReactivacionPropuestaForm(
            data={'motivo_reactivacion': 'Justificación para propuesta no rechazada.'}
        )
        self.assertTrue(form.is_valid())
        form.procesar(prop, self.user_director)
        self.assertEqual(HistorialEstado.objects.filter(propuesta=prop).count(), total_hist_antes)


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


# ==============================================================================
# 8. Pruebas de Vistas Web y API Lazy JSON
# ==============================================================================
class TestVistasAprobacion(BaseAprobacionTestCase):
    """Pruebas de endpoints HTTP, autenticación, control de acceso y respuestas JSON."""

    def test_bandeja_requiere_login(self):
        """La bandeja redirige al login si el usuario no está autenticado."""
        url = reverse('propuestas:aprobacion')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_bandeja_director_sin_carrera_activa_muestra_aviso(self):
        """Si el usuario autenticado no tiene asignación activa de director, avisa sin romper."""
        self.asignacion_director.activo = False
        self.asignacion_director.save()

        self.client.force_login(self.user_director)
        response = self.client.get(reverse('propuestas:aprobacion'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('No tienes asignada una carrera activa', response.content.decode('utf-8'))

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
