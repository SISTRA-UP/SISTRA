"""SISTRA-02 · Aprobación de propuesta: formularios y decisiones individuales.

Solo el responsable de este requisito edita este archivo.
"""

import re

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.parametrizacion.models import TipoRechazo
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado

# BRD 5.3.4 Tabla 10: Mensajes oficiales
MSG_02_01 = 'La propuesta fue aprobada.'
MSG_02_02 = 'Se pidió la modificación y se avisó al estudiante.'
MSG_02_03 = 'La propuesta fue rechazada y se avisó al estudiante.'
MSG_02_04 = 'La propuesta fue reactivada y pasó a En revisión.'
MSG_02_05 = 'Completa los campos obligatorios para continuar.'
MSG_02_06 = 'No es posible reactivar: el estudiante {nombre} ya tiene una propuesta activa.'
MSG_02_07 = 'No puedes cambiar la decisión: el estudiante ya pulsó Subido en UP o inició su informe.'
MSG_02_08 = 'Tu propuesta cambió a {estado}.'

LONGITUD_MAXIMA_TEXTO = 1000
LONGITUD_MINIMA_OBSERVACION = 10

DIAS_SEMAFORO_VERDE = 7
DIAS_SEMAFORO_AMARILLO = 14

RESULTADO_EXITO = 'Éxito'
RESULTADO_BLOQUEADO = 'Bloqueado'
RESULTADO_FALLO = 'Fallo'

OPCIONES_SEMAFORO = [
    ('', 'Todos los semáforos'),
    ('verde', 'Verde (0 a 7 días)'),
    ('amarillo', 'Amarillo (8 a 14 días)'),
    ('rojo', 'Rojo (15+ días)'),
]

OPCIONES_ESTADO_FILTRO = [
    ('', 'Todos los estados'),
    (EstadoTramite.EN_REVISION, EstadoTramite.EN_REVISION),
    (EstadoTramite.APROBADO, EstadoTramite.APROBADO),
    (EstadoTramite.REQUIERE_MODIFICACION, EstadoTramite.REQUIERE_MODIFICACION),
    (EstadoTramite.RECHAZADO, EstadoTramite.RECHAZADO),
]


class PropuestaBloqueadaError(Exception):
    """Regla RN-02-04 / EX-05: El estudiante ya pulsó Subido en UP o inició informe."""


class ReactivacionInvalidaError(Exception):
    """Regla RG-05 / EX-02: El estudiante ya registra otra propuesta activa en la carrera."""


def sanitizar_texto(valor: str) -> str:
    """Elimina etiquetas HTML y espacios sobrantes"""
    return re.sub(r'<[^>]*?>', '', valor.strip()) if valor else ''


def calcular_semaforo(propuesta: Propuesta) -> dict:
    """Calcula días corridos y color del semáforo (RG-07). Pausa en estados no activos."""
    ahora = timezone.now()
    fecha_base = propuesta.fecha_envio or propuesta.fecha_actualizacion or propuesta.fecha_creacion
    dias = max(0, (ahora - fecha_base).days)
    estado = propuesta.estado

    if estado != EstadoTramite.EN_REVISION:
        return {
            'dias': dias,
            'color': 'neutro',
            'clase_badge': 'text-bg-light border text-secondary',
            'clase_fila': '',
            'pausado': True,
            'tooltip': f'Semáforo detenido en {dias} días (Estado: {estado}).',
        }

    if dias <= DIAS_SEMAFORO_VERDE:
        return {
            'dias': dias,
            'color': 'verde',
            'clase_badge': 'text-bg-success',
            'clase_fila': 'table-success-subtle',
            'pausado': False,
            'tooltip': f'Semáforo Verde ({dias} días sin revisión desde su envío).',
        }
    elif dias <= DIAS_SEMAFORO_AMARILLO:
        return {
            'dias': dias,
            'color': 'amarillo',
            'clase_badge': 'text-bg-warning text-dark',
            'clase_fila': 'table-warning-subtle',
            'pausado': False,
            'tooltip': f'Alerta Amarilla ({dias} días acumulados sin revisión).',
        }
    return {
        'dias': dias,
        'color': 'rojo',
        'clase_badge': 'text-bg-danger',
        'clase_fila': 'table-danger-subtle',
        'pausado': False,
        'tooltip': f'Alerta Roja: Prioridad Alta ({dias} días acumulados sin revisión).',
    }


def puede_revertir_aprobacion(propuesta: Propuesta) -> tuple[bool, str]:
    """Comprueba RN-02-04 / EX-05: Bloquea si tiene cargue vigente en UP o informe iniciado."""
    if propuesta.estado != EstadoTramite.APROBADO:
        return True, ''

    cargue_bloqueante = CargueUp.objects.filter(
        propuesta=propuesta,
        estado_verificacion__in=[EstadoVerificacion.PENDIENTE, EstadoVerificacion.APROBADO_EN_UP],
    ).exists()

    if cargue_bloqueante or Informe.objects.filter(propuesta=propuesta).exists():
        return False, MSG_02_07

    return True, ''


def _auditar(
    usuario,
    accion: str,
    propuesta: Propuesta | None = None,
    id_registro: int | None = None,
    estado_anterior: str | None = None,
    estado_nuevo: str = '',
    tipo_rechazo: str = '',
    observacion: str = '',
    motivo_reactivacion: str = '',
    resultado: str = RESULTADO_EXITO,
    detalle_extra: str = '',
) -> None:
    """Guarda registro inmutable en seguimiento.auditoria con los datos del BRD §5.3.1."""
    partes = []
    if propuesta:
        try:
            u_est = propuesta.proceso.estudiante_carrera.estudiante.usuario
            partes.extend([f'Cédula: {u_est.cedula}', f'Estudiante: {u_est.nombre}'])
        except Exception:
            pass
        partes.append(f"Días semáforo: {calcular_semaforo(propuesta)['dias']}")

    if estado_anterior or estado_nuevo:
        partes.append(f"Transición: {estado_anterior or 'N/A'} -> {estado_nuevo}")
    if tipo_rechazo:
        partes.append(f'Causal: {tipo_rechazo}')
    if observacion or motivo_reactivacion:
        partes.append(f'Observación: {observacion or motivo_reactivacion}')
    if detalle_extra:
        partes.append(f'Detalle: {detalle_extra}')

    Auditoria.objects.create(
        usuario=usuario if getattr(usuario, 'is_authenticated', False) else None,
        accion=accion[:100],
        tabla_afectada='propuesta',
        id_registro_afectado=id_registro or (propuesta.pk if propuesta else None),
        detalle=' | '.join(partes),
        resultado=resultado[:30],
        fecha_hora=timezone.now(),
    )


def _notificar_estudiante(propuesta: Propuesta, mensaje: str) -> None:
    """Genera aviso dentro de SISTRA para el estudiante (MSG-02-08 / RG-08)."""
    Notificacion.objects.create(
        usuario=propuesta.proceso.estudiante_carrera.estudiante.usuario,
        propuesta=propuesta,
        tipo='Cambio de estado',
        mensaje=mensaje,
        fecha_creacion=timezone.now(),
    )


def aplicar_transicion(
    propuesta: Propuesta,
    usuario,
    estado_nuevo: str,
    tipo_accion: str,
    accion_auditoria: str,
    tipo_rechazo: TipoRechazo | None = None,
    observacion: str = '',
    motivo_reactivacion: str = '',
    mensaje_notif: str = '',
) -> None:
    """Aplica el cambio de estado, registra historial, notifica y audita."""
    estado_anterior = propuesta.estado
    propuesta.estado = estado_nuevo
    propuesta.save()

    HistorialEstado.objects.create(
        propuesta=propuesta,
        usuario=usuario,
        tipo_rechazo=tipo_rechazo,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        observacion=observacion,
        motivo_reactivacion=motivo_reactivacion,
        tipo_accion=tipo_accion,
        fecha_hora=timezone.now(),
    )

    notif = mensaje_notif or f'Tu propuesta cambió a {estado_nuevo}.'
    if not mensaje_notif and observacion:
        notif += f' Observación del Director: {observacion}'

    _notificar_estudiante(propuesta, notif)

    _auditar(
        usuario=usuario,
        accion=accion_auditoria,
        propuesta=propuesta,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        tipo_rechazo=tipo_rechazo.nombre if tipo_rechazo else '',
        observacion=observacion,
        motivo_reactivacion=motivo_reactivacion,
        resultado=RESULTADO_EXITO,
    )


class FiltroBandejaPropuestasForm(forms.Form):
    """Barra superior de búsqueda general y filtros (BRD 5.3.2)."""

    buscar = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Buscar por nombre, cédula, código o título...', 'id': 'txt-busq-gen'}
        ),
    )
    estado = forms.ChoiceField(
        required=False, choices=OPCIONES_ESTADO_FILTRO, widget=forms.Select(attrs={'class': 'form-select', 'id': 'cmb-est'})
    )
    semaforo = forms.ChoiceField(
        required=False, choices=OPCIONES_SEMAFORO, widget=forms.Select(attrs={'class': 'form-select', 'id': 'cmb-dias'})
    )

    def clean_buscar(self) -> str:
        return sanitizar_texto(self.cleaned_data.get('buscar', ''))


class AprobacionPropuestaForm(forms.Form):
    """Aprobación individual con observación opcional."""

    observacion = forms.CharField(
        required=False,
        max_length=LONGITUD_MAXIMA_TEXTO,
        widget=forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Observaciones (opcional)...', 'maxlength': LONGITUD_MAXIMA_TEXTO, 'id': 'txt-obs-aprobar'}
        ),
    )

    def clean_observacion(self) -> str:
        return sanitizar_texto(self.cleaned_data.get('observacion', ''))

    def procesar(self, propuesta: Propuesta, usuario) -> None:
        """Aplica la aprobación de forma atómica."""
        with transaction.atomic():
            lock = Propuesta.objects.select_for_update().select_related('proceso__estudiante_carrera__estudiante__usuario').get(pk=propuesta.pk)
            if lock.estado == EstadoTramite.RECHAZADO:
                raise ValidationError('Una propuesta rechazada solo puede ser reactivada mediante el modal de reactivación justificando el motivo.')
            if lock.estado == EstadoTramite.APROBADO:
                return
            if lock.estado != EstadoTramite.EN_REVISION:
                raise ValidationError(f"Solo se puede aprobar una propuesta en estado 'En revisión' (estado actual: {lock.estado}).")
            obs = self.cleaned_data.get('observacion', '')
            notif = 'Tu propuesta cambió a Aprobado.' + (f' Observación del Director: {obs}' if obs else '')
            aplicar_transicion(lock, usuario, EstadoTramite.APROBADO, 'Aprobación', 'APROBAR_PROPUESTA', observacion=obs, mensaje_notif=notif)


class ModificacionPropuestaForm(forms.Form):
    """Solicitud de modificación con observación obligatoria (RN-02-02)."""

    observacion = forms.CharField(
        required=True,
        min_length=LONGITUD_MINIMA_OBSERVACION,
        max_length=LONGITUD_MAXIMA_TEXTO,
        widget=forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Detalle las correcciones que debe realizar el estudiante...', 'maxlength': LONGITUD_MAXIMA_TEXTO, 'id': 'txt-obs-modificar'}
        ),
        error_messages={'required': 'Debe ingresar obligatoriamente las correcciones que debe realizar el estudiante.'},
    )

    def clean_observacion(self) -> str:
        return sanitizar_texto(self.cleaned_data['observacion'])

    def procesar(self, propuesta: Propuesta, usuario) -> None:
        """Aplica la solicitud de modificación de forma atómica."""
        if propuesta.estado == EstadoTramite.APROBADO:
            puede, motivo = puede_revertir_aprobacion(propuesta)
            if not puede:
                _auditar(
                    usuario,
                    'MODIFICAR_PROPUESTA_BLOQUEADA',
                    propuesta,
                    estado_anterior=propuesta.estado,
                    estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
                    observacion=self.cleaned_data['observacion'],
                    detalle_extra=motivo,
                    resultado=RESULTADO_BLOQUEADO,
                )
                raise PropuestaBloqueadaError(motivo)

        with transaction.atomic():
            lock = Propuesta.objects.select_for_update().select_related('proceso__estudiante_carrera__estudiante__usuario').get(pk=propuesta.pk)
            if lock.estado == EstadoTramite.RECHAZADO:
                raise ValidationError('Una propuesta rechazada solo puede ser reactivada mediante el modal de reactivación justificando el motivo.')
            if lock.estado == EstadoTramite.REQUIERE_MODIFICACION:
                return
            if lock.estado not in [EstadoTramite.EN_REVISION, EstadoTramite.APROBADO]:
                raise ValidationError(f"Solo se puede solicitar modificación a propuestas en 'En revisión' o 'Aprobado' (estado actual: {lock.estado}).")
            if lock.estado == EstadoTramite.APROBADO:
                puede, motivo = puede_revertir_aprobacion(lock)
                if not puede:
                    raise PropuestaBloqueadaError(motivo)
            obs = self.cleaned_data['observacion']
            aplicar_transicion(lock, usuario, EstadoTramite.REQUIERE_MODIFICACION, 'Solicitud de modificación', 'SOLICITAR_MODIFICACION_PROPUESTA', observacion=obs, mensaje_notif=f'Tu propuesta cambió a Requiere modificación. Observación del Director: {obs}')


class RechazoPropuestaForm(forms.Form):
    """Rechazo individual con causal y observación obligatorias (RN-02-01)."""

    tipo_rechazo = forms.ModelChoiceField(
        queryset=TipoRechazo.objects.none(),
        required=True,
        empty_label='Seleccione una causal de rechazo...',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'cmb-tipo-rec'}),
        error_messages={'required': 'Es obligatorio seleccionar un tipo de rechazo.'},
    )
    observacion = forms.CharField(
        required=True,
        min_length=LONGITUD_MINIMA_OBSERVACION,
        max_length=LONGITUD_MAXIMA_TEXTO,
        widget=forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Detalle el motivo del rechazo de la propuesta...', 'maxlength': LONGITUD_MAXIMA_TEXTO, 'id': 'txt-obs-rechazar'}
        ),
        error_messages={'required': 'Es obligatorio registrar el detalle del rechazo en la observación.'},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo_rechazo'].queryset = TipoRechazo.objects.filter(estado=Estado.ACTIVO).order_by('nombre')

    def clean_observacion(self) -> str:
        return sanitizar_texto(self.cleaned_data['observacion'])

    def procesar(self, propuesta: Propuesta, usuario) -> None:
        """Aplica el rechazo de forma atómica."""
        if propuesta.estado == EstadoTramite.APROBADO:
            puede, motivo = puede_revertir_aprobacion(propuesta)
            if not puede:
                _auditar(
                    usuario,
                    'RECHAZAR_PROPUESTA_BLOQUEADA',
                    propuesta,
                    estado_anterior=propuesta.estado,
                    estado_nuevo=EstadoTramite.RECHAZADO,
                    tipo_rechazo=str(self.cleaned_data['tipo_rechazo']),
                    observacion=self.cleaned_data['observacion'],
                    detalle_extra=motivo,
                    resultado=RESULTADO_BLOQUEADO,
                )
                raise PropuestaBloqueadaError(motivo)

        with transaction.atomic():
            lock = Propuesta.objects.select_for_update().select_related('proceso__estudiante_carrera__estudiante__usuario').get(pk=propuesta.pk)
            if lock.estado == EstadoTramite.RECHAZADO:
                return
            if lock.estado not in [EstadoTramite.EN_REVISION, EstadoTramite.APROBADO]:
                raise ValidationError(f"Solo se puede rechazar una propuesta en estado 'En revisión' o 'Aprobado' (estado actual: {lock.estado}).")
            if lock.estado == EstadoTramite.APROBADO:
                puede, motivo = puede_revertir_aprobacion(lock)
                if not puede:
                    raise PropuestaBloqueadaError(motivo)
            tipo_rec = self.cleaned_data['tipo_rechazo']
            obs = self.cleaned_data['observacion']
            aplicar_transicion(lock, usuario, EstadoTramite.RECHAZADO, 'Rechazo', 'RECHAZAR_PROPUESTA', tipo_rechazo=tipo_rec, observacion=obs, mensaje_notif=f'Tu propuesta cambió a Rechazado ({tipo_rec.nombre}). Observación del Director: {obs}')


class ReactivacionPropuestaForm(forms.Form):
    """Reactivación de propuesta rechazada por error (RG-04). Retorna a 'En revisión'."""

    motivo_reactivacion = forms.CharField(
        required=True,
        min_length=LONGITUD_MINIMA_OBSERVACION,
        max_length=LONGITUD_MAXIMA_TEXTO,
        widget=forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Justifique el motivo por el cual reactiva esta propuesta...', 'maxlength': LONGITUD_MAXIMA_TEXTO, 'id': 'txt-motivo-rea'}
        ),
        error_messages={'required': 'Por políticas de auditoría, es obligatorio registrar la justificación de reactivación.'},
    )

    def clean_motivo_reactivacion(self) -> str:
        return sanitizar_texto(self.cleaned_data['motivo_reactivacion'])

    def procesar(self, propuesta: Propuesta, usuario) -> None:
        """Aplica la reactivación retornando la propuesta a En revisión."""
        if propuesta.estado != EstadoTramite.RECHAZADO:
            return
        if propuesta.archivada:
            raise ReactivacionInvalidaError('Esta propuesta ya fue archivada y no puede ser reactivada por políticas de conservación.')

        u_est = propuesta.proceso.estudiante_carrera.estudiante.usuario
        if Propuesta.objects.filter(proceso=propuesta.proceso, archivada=False).exclude(estado=EstadoTramite.RECHAZADO).exclude(pk=propuesta.pk).exists():
            msg_err = MSG_02_06.format(nombre=u_est.nombre)
            _auditar(
                usuario,
                'REACTIVAR_PROPUESTA_BLOQUEADA',
                propuesta,
                estado_anterior=propuesta.estado,
                estado_nuevo=EstadoTramite.EN_REVISION,
                motivo_reactivacion=self.cleaned_data['motivo_reactivacion'],
                detalle_extra=msg_err,
                resultado=RESULTADO_BLOQUEADO,
            )
            raise ReactivacionInvalidaError(msg_err)

        with transaction.atomic():
            lock = Propuesta.objects.select_for_update().select_related('proceso__estudiante_carrera__estudiante__usuario').get(pk=propuesta.pk)
            if lock.estado != EstadoTramite.RECHAZADO:
                return
            motivo = self.cleaned_data['motivo_reactivacion']
            aplicar_transicion(lock, usuario, EstadoTramite.EN_REVISION, 'Reactivación', 'REACTIVAR_PROPUESTA', motivo_reactivacion=motivo, mensaje_notif=f'Tu propuesta fue reactivada y pasó a En revisión. Motivo del Director: {motivo}')
