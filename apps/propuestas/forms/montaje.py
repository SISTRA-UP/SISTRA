"""SISTRA-01 · Montaje de propuesta – Trabajo Social: formularios.

Solo el responsable de este requisito edita este archivo.
"""
from django import forms
from django.core.exceptions import ValidationError

from apps.propuestas.models import EstadoTramite, Propuesta, SectorEntidad

# ---------------------------------------------------------------------------
# Mensajes oficiales del BRD SISTRA-01
# ---------------------------------------------------------------------------
MSG_01_01 = 'Tu propuesta se guardó como borrador.'
MSG_01_02 = 'Tu propuesta se envió y quedó en revisión. Te avisaremos cuando tu Director la revise.'
MSG_01_03 = 'El archivo no corresponde a la plantilla de SISTRA o fue modificada su estructura. Descarga la plantilla de nuevo.'
MSG_01_04 = 'El archivo debe ser .docx y no superar el tamaño permitido.'
MSG_01_05 = 'Completa este campo.'
MSG_01_06 = 'La fecha de fin no puede ser anterior a la de inicio.'
MSG_01_07 = 'No pudimos guardar tu propuesta. Inténtalo de nuevo.'
MSG_01_08 = 'Ya tienes una propuesta activa. Solo puedes crear otra si la actual fue rechazada.'

# ---------------------------------------------------------------------------
# Campos y estados
# ---------------------------------------------------------------------------
CAMPOS_OBLIGATORIOS_ENVIO = (
    'titulo',
    'entidad',
    'sector_entidad',
    'sector',
    'zona',
    'area',
    'unidad',
    'poblacion_beneficiada',
    'identificacion_poblacion',
    'resena_historica',
    'identificacion_necesidad',
    'justificacion',
    'objetivos',
    'referente_teorico',
    'propuesta_social',
    'impacto_social',
    'fecha_inicio',
    'fecha_fin',
)

ESTADOS_EDITABLES = (
    EstadoTramite.BORRADOR,
    EstadoTramite.REQUIERE_MODIFICACION,
)

MAX_UPLOAD_MB = 10


class PropuestaMontajeForm(forms.ModelForm):
    """Formulario para registro y edición de la propuesta por el estudiante (SISTRA-01).

    - Ningún campo es obligatorio en HTML mientras es Borrador (permite guardado parcial).
    - La obligatoriedad total (100 %) se exige al pulsar 'enviar'.
    - Si la propuesta no está en estado editable, todos los campos se bloquean (disabled).
    """

    class Meta:
        model = Propuesta
        fields = [
            'titulo',
            'entidad',
            'sector_entidad',
            'sector',
            'zona',
            'area',
            'unidad',
            'poblacion_beneficiada',
            'identificacion_poblacion',
            'resena_historica',
            'identificacion_necesidad',
            'justificacion',
            'objetivos',
            'referente_teorico',
            'propuesta_social',
            'impacto_social',
            'fecha_inicio',
            'fecha_fin',
        ]
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Título claro y descriptivo del proyecto'}),
            'entidad': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombre de la entidad, institución u organización'}),
            'sector_entidad': forms.Select(attrs={'class': 'form-select'}),
            'sector': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Educativo, Comunitario, Salud, Ambiental'}),
            'zona': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Urbana, Rural, Periférica'}),
            'area': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Área temática de intervención'}),
            'unidad': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Barrio, vereda o unidad ejecutora'}),
            'poblacion_beneficiada': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Cantidad y perfil de los beneficiarios'}),
            'identificacion_poblacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Características sociodemográficas de la población'}),
            'resena_historica': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Antecedentes, origen y trayectoria institucional'}),
            'identificacion_necesidad': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Planteamiento y descripción del problema o necesidad identificada'}),
            'justificacion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Por qué y para qué se realiza la intervención social'}),
            'objetivos': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Objetivo general y objetivos específicos del Trabajo Social'}),
            'referente_teorico': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Fundamentos teóricos, legales o conceptuales que sustentan la propuesta'}),
            'propuesta_social': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Metodología, fases, estrategias y actividades planificadas'}),
            'impacto_social': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Transformaciones, beneficios o cambios esperados en la comunidad'}),
            'fecha_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'fecha_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        # Labels exactos de la tabla de campos del BRD SISTRA-01
        labels = {
            'titulo': 'Título de la propuesta',
            'entidad': 'Entidad',
            'sector_entidad': 'Sector de la entidad',
            'sector': 'Sector',
            'zona': 'Zona',
            'area': 'Área',
            'unidad': 'Unidad',
            'poblacion_beneficiada': 'Población beneficiada',
            'identificacion_poblacion': 'Identificación de la población',
            'resena_historica': 'Reseña histórica',
            'identificacion_necesidad': 'Identificación de la necesidad',
            'justificacion': 'Justificación',
            'objetivos': 'Objetivos',
            'referente_teorico': 'Referente teórico',
            'propuesta_social': 'Propuesta social',
            'impacto_social': 'Impacto social',
            'fecha_inicio': 'Fecha estimada de inicio',
            'fecha_fin': 'Fecha estimada de finalización',
        }

    def __init__(self, *args, accion: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.accion = accion
        self.bloqueado = bool(self.instance and self.instance.pk) and (
            self.instance.estado not in ESTADOS_EDITABLES
        )

        for nombre, campo in self.fields.items():
            campo.required = False  # En borrador ningún campo es obligatorio
            campo.es_obligatorio_envio = nombre in CAMPOS_OBLIGATORIOS_ENVIO
            if campo.es_obligatorio_envio:
                campo.widget.attrs['data-required'] = 'true'
            if self.bloqueado:
                campo.disabled = True

    def clean(self):
        cleaned = super().clean()
        if self.bloqueado:
            raise ValidationError('La propuesta está bloqueada y no admite modificaciones en su estado actual.')

        inicio = cleaned.get('fecha_inicio')
        fin = cleaned.get('fecha_fin')
        if inicio and fin and fin < inicio:
            self.add_error('fecha_fin', MSG_01_06)

        if self.accion == 'enviar':
            faltantes = []
            for campo in CAMPOS_OBLIGATORIOS_ENVIO:
                val = cleaned.get(campo)
                if val is None or (isinstance(val, str) and not val.strip()):
                    self.add_error(campo, MSG_01_05)
                    label = self.fields[campo].label or campo
                    faltantes.append(label)
            if faltantes:
                raise ValidationError(
                    'Para enviar la propuesta a revisión se deben completar todos los campos obligatorios (100 % de avance). '
                    f'Faltan: {", ".join(faltantes)}.'
                )
        return cleaned

    def calcular_avance(self) -> int:
        """Calcula el porcentaje de campos obligatorios diligenciados (0-100 %)."""
        datos = self.cleaned_data if hasattr(self, 'cleaned_data') and self.cleaned_data else (
            self.initial or {}
        )
        if not datos and self.instance:
            datos = {
                c: getattr(self.instance, c, None)
                for c in CAMPOS_OBLIGATORIOS_ENVIO
            }

        llenos = 0
        for campo in CAMPOS_OBLIGATORIOS_ENVIO:
            val = datos.get(campo)
            if val is not None and str(val).strip():
                llenos += 1
        return round(100 * llenos / len(CAMPOS_OBLIGATORIOS_ENVIO)) if CAMPOS_OBLIGATORIOS_ENVIO else 0


class CargaPlantillaWordForm(forms.Form):
    """Carga de plantilla Word (.docx) para autocompletar el formulario (BRD SISTRA-01)."""

    archivo = forms.FileField(
        label='Plantilla Word (.docx)',
        widget=forms.ClearableFileInput(attrs={'accept': '.docx', 'class': 'form-control'}),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if not archivo.name.lower().endswith('.docx') or archivo.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise ValidationError(MSG_01_04)
        return archivo
