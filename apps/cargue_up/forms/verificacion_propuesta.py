"""SISTRA-05 · Notificación de cargue UP – Director: formularios.

Solo el responsable de este requisito edita este archivo.

El Director verifica en la Plataforma UP las propuestas en «Subido en UP» y marca
«Aprobado en UP» o «Rechazado en UP». Aquí viven el alcance del Director, las
validaciones de entrada y los textos del BRD (sección 5.6). Sigue el mismo
patrón que SISTRA-09 (verificacion_informe), aplicado a la propuesta.
"""

import re

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.personas.models import Director, DirectorCarrera
from apps.propuestas.models import EstadoTramite, Propuesta

# El Director ya recibe este permiso desde SISTRA-02 (propuestas/0002).
PERMISO_VERIFICAR = 'propuesta.aprobar'

ACCION_AUDITORIA_VERIFICAR = 'verificacion_propuesta'
ACCION_AUDITORIA_CORREGIR = 'correccion_verif_propuesta'  # tipo_accion admite 30 caracteres
ACCION_AUDITORIA_DENEGADO = 'intento_verificacion_propuesta'
TIPO_NOTIFICACION_VERIFICACION = 'verificacion_propuesta'
TIPO_NOTIFICACION_CORRECCION = 'correccion_verif_propuesta'

RESULTADO_EXITO = 'Éxito'
RESULTADO_FALLO = 'Fallo'
RESULTADO_BLOQUEADO = 'Bloqueado'

LONGITUD_TEXTO = 1000
LONGITUD_BUSQUEDA = 100
POR_PAGINA = 20

VISTA_PENDIENTES = 'pendientes'
VISTA_VERIFICADOS = 'verificados'

# Mensajes de la matriz 5.6.4 del BRD.
MSG_05_01 = 'Registraste que la propuesta coincide. El estudiante ya puede montar su informe.'
MSG_05_02 = (
    'Registraste que la propuesta no coincide. '
    'Se avisó al estudiante para que la cargue de nuevo.'
)
MSG_05_04 = 'Esta propuesta ya no está pendiente de verificación.'
MSG_05_05 = 'Escribe la observación o el motivo para continuar.'
MSG_05_06 = 'Se corrigió la verificación y se avisó al estudiante.'
# Mensajes de apoyo que el BRD no define (texto de interfaz, sin valor institucional).
MSG_05_CORRECCION_NO_DISPONIBLE = 'Esta verificación ya no se puede corregir.'
MSG_05_ERROR = 'No fue posible guardar la verificación. No se guardaron cambios; inténtalo de nuevo.'
MSG_05_SIN_HTML = 'No uses HTML ni scripts en el texto.'
MSG_05_DENEGADO = 'Tu sesión expiró o no tienes permiso para consultar esta información.'

_ETIQUETA_HTML = re.compile(r'<[^>]*>|[<>]')


def mensaje_notificacion(resultado: str, observacion: str, *, corregida: bool = False) -> str:
    """MSG-05-03 para el estudiante (también para correcciones, con prefijo)."""
    if resultado == EstadoVerificacion.APROBADO_EN_UP:
        cuerpo = 'Aprobado en UP.'
    else:
        cuerpo = (
            'lo cargado no coincide con lo aprobado; cárgalo de nuevo y pulsa Subido en UP. '
            f'Observación del Director: {observacion}'
        )
    inicio = 'Tu Director corrigió su verificación de la Plataforma UP: ' if corregida else (
        'Tu Director revisó la Plataforma UP: '
    )
    return inicio + cuerpo


def _texto_sin_html(valor: str) -> str:
    if _ETIQUETA_HTML.search(valor):
        raise forms.ValidationError(MSG_05_SIN_HTML)
    return valor


def _campo_texto(etiqueta: str, ayuda: str) -> forms.CharField:
    return forms.CharField(
        label=etiqueta,
        required=False,
        strip=True,
        max_length=LONGITUD_TEXTO,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': ayuda}),
    )


class BusquedaForm(forms.Form):
    """TXT-BUSCAR: filtra por nombre o cédula; no persiste."""

    buscar = forms.CharField(
        label='Buscar',
        required=False,
        strip=True,
        max_length=LONGITUD_BUSQUEDA,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'Nombre o cédula del estudiante'}
        ),
    )


class DecisionForm(forms.Form):
    """BTN-APR-UP / BTN-REC-UP con TXT-OBS-UP (obligatoria al rechazar)."""

    resultado = forms.ChoiceField(
        choices=[
            (EstadoVerificacion.APROBADO_EN_UP, 'Aprobado en UP'),
            (EstadoVerificacion.RECHAZADO_EN_UP, 'Rechazado en UP'),
        ],
        widget=forms.HiddenInput,
    )
    id_cargue = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    observacion = _campo_texto('Observación para el estudiante', 'Escribe qué no coincide.')

    def clean_observacion(self):
        return _texto_sin_html(self.cleaned_data['observacion'])

    def clean(self):
        datos = super().clean()
        resultado = datos.get('resultado')
        if resultado == EstadoVerificacion.RECHAZADO_EN_UP:
            if not datos.get('observacion') and 'observacion' not in self.errors:
                self.add_error('observacion', MSG_05_05)
        elif resultado == EstadoVerificacion.APROBADO_EN_UP:
            datos['observacion'] = ''
        return datos


class CorreccionForm(forms.Form):
    """TXT-MOTIVO-CORR (siempre) y TXT-OBS-UP (si el nuevo resultado es Rechazado en UP)."""

    resultado = forms.ChoiceField(
        choices=[
            (EstadoVerificacion.APROBADO_EN_UP, 'Aprobado en UP'),
            (EstadoVerificacion.RECHAZADO_EN_UP, 'Rechazado en UP'),
        ],
        widget=forms.HiddenInput,
    )
    id_cargue = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    motivo = _campo_texto('Motivo de la corrección', 'Explica por qué corriges la verificación.')
    observacion = _campo_texto('Observación para el estudiante', 'Escribe qué no coincide.')

    def __init__(self, *args, resultado_nuevo: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resultado_nuevo = resultado_nuevo

    def clean_motivo(self):
        return _texto_sin_html(self.cleaned_data['motivo'])

    def clean_observacion(self):
        return _texto_sin_html(self.cleaned_data['observacion'])

    def clean(self):
        datos = super().clean()
        if not datos.get('motivo') and 'motivo' not in self.errors:
            self.add_error('motivo', MSG_05_05)
        if self.resultado_nuevo == EstadoVerificacion.RECHAZADO_EN_UP:
            if not datos.get('observacion') and 'observacion' not in self.errors:
                self.add_error('observacion', MSG_05_05)
        else:
            datos['observacion'] = ''
        return datos


def director_y_carreras(usuario) -> tuple[Director, list[int]]:
    """Perfil de Director y carreras con asignación activa; el servidor lo revalida siempre."""
    if (
        not usuario.is_authenticated
        or not usuario.is_active
        or usuario.es_administrador
        or not usuario.has_perm(PERMISO_VERIFICAR)
    ):
        raise PermissionDenied(MSG_05_DENEGADO)

    asignaciones = list(
        DirectorCarrera.objects.filter(director__usuario=usuario, activo=True)
        .select_related('director')
    )
    if not asignaciones:
        raise PermissionDenied(MSG_05_DENEGADO)
    return asignaciones[0].director, [a.carrera_id for a in asignaciones]


def _ultimo_cargue(campo: str):
    return Subquery(
        CargueUp.objects.filter(propuesta=OuterRef('pk'))
        .order_by('-fecha_declaracion', '-pk')
        .values(campo)[:1]
    )


def propuestas_del_director(usuario, *, bloquear: bool = False, etapa_cargue: bool = True):
    """Propuestas de los estudiantes asignados al Director, con la etapa de cargue.

    Anota el último cargue (id, resultado y fecha) para filtrar sin recorrer en Python.
    Con ``bloquear`` serializa decisiones simultáneas sobre la misma propuesta.
    Con ``etapa_cargue=False`` no se filtra por estado: así una acción sobre una propuesta
    que cambió de estado responde con MSG-05-04 (EX-02) en vez de un 404.
    """
    _, carreras = director_y_carreras(usuario)
    propuestas = (
        Propuesta.objects.filter(
            proceso__estudiante_carrera__carrera_id__in=carreras,
            archivada=False,
        )
        .select_related('proceso__estudiante_carrera__estudiante__usuario')
        .annotate(
            id_ultimo_cargue=_ultimo_cargue('pk'),
            resultado_ultimo_cargue=_ultimo_cargue('estado_verificacion'),
            fecha_ultimo_cargue=_ultimo_cargue('fecha_declaracion'),
        )
    )
    if etapa_cargue:
        propuestas = propuestas.filter(
            estado__in=(
                EstadoTramite.APROBADO,
                EstadoTramite.SUBIDO_EN_UP,
                EstadoTramite.APROBADO_EN_UP,
            )
        )
    if bloquear:
        propuestas = propuestas.select_for_update(of=('self',))
    return propuestas


def propuesta_del_director_o_404(
    usuario, id_propuesta: int, *, bloquear: bool = False, etapa_cargue: bool = True
) -> Propuesta:
    """Una propuesta ajena o inexistente responde igual: 404 sin revelar datos."""
    return get_object_or_404(
        propuestas_del_director(usuario, bloquear=bloquear, etapa_cargue=etapa_cargue),
        pk=id_propuesta,
    )


def pendientes(propuestas):
    """RN-05-01: solo se verifica una propuesta en Subido en UP con cargue pendiente."""
    return propuestas.filter(
        estado=EstadoTramite.SUBIDO_EN_UP,
        resultado_ultimo_cargue=EstadoVerificacion.PENDIENTE,
    )


def verificados_corregibles(propuestas):
    """Propuestas cuya última verificación aún se puede corregir (FA-03)."""
    return propuestas.filter(
        Q(estado=EstadoTramite.APROBADO_EN_UP,
          resultado_ultimo_cargue=EstadoVerificacion.APROBADO_EN_UP)
        | Q(estado=EstadoTramite.APROBADO,
            resultado_ultimo_cargue=EstadoVerificacion.RECHAZADO_EN_UP)
    )


def filtrar_por_busqueda(propuestas, texto: str):
    if not texto:
        return propuestas
    ruta = 'proceso__estudiante_carrera__estudiante__usuario'
    return propuestas.filter(
        Q(**{f'{ruta}__nombre__icontains': texto}) | Q(**{f'{ruta}__cedula__icontains': texto})
    )


def resultado_de_correccion(estado_propuesta: str, resultado_ultimo_cargue: str | None) -> str | None:
    """Resultado contrario que se puede registrar, o None si no hay nada que corregir.

    Solo la última verificación se corrige, y mientras la propuesta siga como la
    dejó: si el estudiante ya cargó de nuevo (Subido en UP) no se corrige la anterior.
    """
    if (
        estado_propuesta == EstadoTramite.APROBADO_EN_UP
        and resultado_ultimo_cargue == EstadoVerificacion.APROBADO_EN_UP
    ):
        return EstadoVerificacion.RECHAZADO_EN_UP
    if (
        estado_propuesta == EstadoTramite.APROBADO
        and resultado_ultimo_cargue == EstadoVerificacion.RECHAZADO_EN_UP
    ):
        return EstadoVerificacion.APROBADO_EN_UP
    return None


def estado_propuesta_para(resultado: str) -> str:
    """RN-05-02 / RN-05-03: Rechazado en UP devuelve la propuesta a Aprobado."""
    if resultado == EstadoVerificacion.APROBADO_EN_UP:
        return EstadoTramite.APROBADO_EN_UP
    return EstadoTramite.APROBADO
