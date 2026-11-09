"""SISTRA-02 · Aprobación de propuesta: formulario de acciones masivas.

Solo el responsable de este requisito edita este archivo.
"""

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.parametrizacion.models import Carrera, TipoRechazo
from apps.propuestas.forms.aprobacion import (
    LONGITUD_MAXIMA_TEXTO,
    LONGITUD_MINIMA_OBSERVACION,
    MSG_02_06,
    RESULTADO_BLOQUEADO,
    ReactivacionInvalidaError,
    _auditar,
    aplicar_transicion,
    sanitizar_texto,
)
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.usuarios.models import Estado


class AccionMasivaForm(forms.Form):
    """Acciones en lote: Aprobar masivo, Rechazar masivo, Reactivar masivo (FA-03)."""

    ACCION_APROBAR = 'aprobar'
    ACCION_RECHAZAR = 'rechazar'
    ACCION_REACTIVAR = 'reactivar'

    ACCIONES_PERMITIDAS = [
        (ACCION_APROBAR, 'Aprobar masivo'),
        (ACCION_RECHAZAR, 'Rechazar masivo'),
        (ACCION_REACTIVAR, 'Reactivar masivo'),
    ]

    accion = forms.ChoiceField(choices=ACCIONES_PERMITIDAS, required=True)
    propuestas_ids = forms.CharField(widget=forms.HiddenInput(), required=True)
    tipo_rechazo = forms.ModelChoiceField(
        queryset=TipoRechazo.objects.none(),
        required=False,
        empty_label='Seleccione una causal de rechazo...',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'cmb-tipo-rec-masivo'}),
    )
    observacion = forms.CharField(
        required=False,
        max_length=LONGITUD_MAXIMA_TEXTO,
        widget=forms.Textarea(
            attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Observación o motivo para todas las propuestas seleccionadas...', 'id': 'txt-obs-masivo'}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo_rechazo'].queryset = TipoRechazo.objects.filter(estado=Estado.ACTIVO).order_by('nombre')

    def clean_propuestas_ids(self) -> list[int]:
        # Soporta tanto lista de inputs en HTML (getlist) como cadena separada por comas
        raw_list = self.data.getlist('propuestas_ids') if hasattr(self.data, 'getlist') else []
        elementos = []
        for val in raw_list:
            elementos.extend(str(val).split(','))
        cleaned = self.cleaned_data.get('propuestas_ids', '')
        if isinstance(cleaned, str):
            elementos.extend(cleaned.split(','))
        elif isinstance(cleaned, (list, tuple)):
            for val in cleaned:
                elementos.extend(str(val).split(','))

        ids = list(dict.fromkeys(int(i.strip()) for i in elementos if str(i).strip().isdigit()))
        if not ids:
            raise ValidationError('Debe seleccionar al menos una propuesta.')
        return ids

    def clean(self) -> dict:
        data = super().clean()
        accion = data.get('accion')
        obs = data.get('observacion', '').strip()
        causal = data.get('tipo_rechazo')

        if accion == self.ACCION_RECHAZAR:
            if not causal:
                self.add_error('tipo_rechazo', 'Es obligatorio seleccionar un tipo de rechazo.')
            if len(obs) < LONGITUD_MINIMA_OBSERVACION:
                self.add_error('observacion', f'Es obligatorio ingresar una observación de al menos {LONGITUD_MINIMA_OBSERVACION} caracteres.')
        elif accion == self.ACCION_REACTIVAR:
            if len(obs) < LONGITUD_MINIMA_OBSERVACION:
                self.add_error('observacion', f'Es obligatorio ingresar la justificación de reactivación (mínimo {LONGITUD_MINIMA_OBSERVACION} caracteres).')

        data['observacion'] = sanitizar_texto(obs)
        return data

    def procesar(self, carrera: Carrera, usuario) -> int:
        """Aplica la acción masiva sobre las propuestas seleccionadas de la carrera."""
        accion = self.cleaned_data['accion']
        ids = self.cleaned_data['propuestas_ids']
        tipo_rechazo = self.cleaned_data.get('tipo_rechazo')
        observacion = self.cleaned_data.get('observacion', '')

        propuestas = list(
            Propuesta.objects.filter(pk__in=ids, proceso__estudiante_carrera__carrera=carrera)
            .select_related('proceso__estudiante_carrera__estudiante__usuario')
        )

        if not propuestas:
            return 0
        if len(propuestas) != len(ids):
            raise ValidationError('Una o más propuestas seleccionadas no pertenecen a la carrera activa del Director.')

        # Validar compatibilidad de estados según acción (RN-02-03)
        if accion in [self.ACCION_APROBAR, self.ACCION_RECHAZAR]:
            if any(p.estado != EstadoTramite.EN_REVISION for p in propuestas):
                raise ValidationError("Para aprobar o rechazar de forma masiva, todas las propuestas deben estar exclusivamente en estado 'En revisión'.")
        elif accion == self.ACCION_REACTIVAR:
            if any(p.estado != EstadoTramite.RECHAZADO or p.archivada for p in propuestas):
                raise ValidationError("Para reactivar de forma masiva, todas las propuestas deben estar en estado 'Rechazado' y no estar archivadas.")

            # Validar colisión RG-05 / EX-02 en lote (sin N+1)
            procesos_ids = [p.proceso_id for p in propuestas]
            if len(procesos_ids) != len(set(procesos_ids)):
                nombre = propuestas[0].proceso.estudiante_carrera.estudiante.usuario.nombre
                raise ReactivacionInvalidaError(MSG_02_06.format(nombre=nombre))

            otras = list(
                Propuesta.objects.filter(proceso_id__in=procesos_ids, archivada=False)
                .exclude(estado=EstadoTramite.RECHAZADO)
                .exclude(pk__in=ids)
                .select_related('proceso__estudiante_carrera__estudiante__usuario')
            )
            if otras:
                colision = otras[0]
                nombre = colision.proceso.estudiante_carrera.estudiante.usuario.nombre
                msg_err = MSG_02_06.format(nombre=nombre)
                prop_lote = next(p for p in propuestas if p.proceso_id == colision.proceso_id)
                _auditar(usuario, 'REACTIVACION_MASIVA_BLOQUEADA', prop_lote, detalle_extra=msg_err, resultado=RESULTADO_BLOQUEADO)
                raise ReactivacionInvalidaError(msg_err)

        with transaction.atomic():
            propuestas_mutar = list(
                Propuesta.objects.select_for_update()
                .filter(pk__in=ids)
                .select_related('proceso__estudiante_carrera__estudiante__usuario')
            )

            procesadas = 0
            for prop in propuestas_mutar:
                if accion == self.ACCION_APROBAR:
                    estado_nuevo, tipo_accion, accion_aud = EstadoTramite.APROBADO, 'Aprobación masiva', 'APROBACION_MASIVA'
                    motivo_rea, obs_hist = '', observacion
                    msg_notif = 'Tu propuesta cambió a Aprobado.' + (f' Observación del Director: {observacion}' if observacion else '')
                elif accion == self.ACCION_RECHAZAR:
                    estado_nuevo, tipo_accion, accion_aud = EstadoTramite.RECHAZADO, 'Rechazo masivo', 'RECHAZO_MASIVO'
                    motivo_rea, obs_hist = '', observacion
                    msg_notif = f'Tu propuesta cambió a Rechazado ({tipo_rechazo.nombre}). Observación del Director: {observacion}'
                else:
                    estado_nuevo, tipo_accion, accion_aud = EstadoTramite.EN_REVISION, 'Reactivación masiva', 'REACTIVACION_MASIVA'
                    motivo_rea, obs_hist = observacion, ''
                    msg_notif = f'Tu propuesta fue reactivada y pasó a En revisión. Motivo del Director: {observacion}'

                aplicar_transicion(
                    propuesta=prop,
                    usuario=usuario,
                    estado_nuevo=estado_nuevo,
                    tipo_accion=tipo_accion,
                    accion_auditoria=accion_aud,
                    tipo_rechazo=tipo_rechazo if accion == self.ACCION_RECHAZAR else None,
                    observacion=obs_hist,
                    motivo_reactivacion=motivo_rea,
                    mensaje_notif=msg_notif,
                )
                procesadas += 1

            return procesadas
