"""SISTRA-14 · Dashboard: formularios.

Solo el responsable de este requisito edita este archivo.
"""
"""Formularios de filtrado y búsqueda del dashboard (SISTRA-14)."""

from django import forms

from apps.parametrizacion.models import Carrera, Facultad, PeriodoAcademico
from apps.propuestas.models import EstadoTramite
from apps.usuarios.models import Estado, Rol

OPCIONES_SEMAFORO = (
    ('', 'Todos los tiempos'),
    ('verde', 'Al día (Verde)'),
    ('amarillo', 'Próximo a vencer (Amarillo)'),
    ('rojo', 'Atrasado (Rojo)'),
)


class FiltroDirectorForm(forms.Form):
    """Filtros de la bandeja de seguimiento para el rol Director."""

    q = forms.CharField(
        required=False,
        label='Buscar estudiante o código',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Nombre, cédula, correo o código...',
            }
        ),
    )
    estado = forms.ChoiceField(
        required=False,
        label='Estado del trámite',
        choices=[('', 'Todos los estados'), *EstadoTramite.choices],
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    semaforo = forms.ChoiceField(
        required=False,
        label='Semáforo de revisión',
        choices=OPCIONES_SEMAFORO,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )


class FiltroAdministradorForm(forms.Form):
    """Filtros globales para el rol Administrador (ADMO)."""

    q = forms.CharField(
        required=False,
        label='Buscar',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control form-control-sm',
                'placeholder': 'Estudiante, director, correo o código...',
            }
        ),
    )
    facultad = forms.ModelChoiceField(
        required=False,
        label='Facultad',
        queryset=Facultad.objects.filter(estado=Estado.ACTIVO).order_by('nombre'),
        empty_label='Todas las facultades',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    carrera = forms.ModelChoiceField(
        required=False,
        label='Carrera',
        queryset=Carrera.objects.filter(estado=Estado.ACTIVO)
        .select_related('facultad')
        .order_by('nombre'),
        empty_label='Todas las carreras',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    periodo = forms.ModelChoiceField(
        required=False,
        label='Periodo académico',
        queryset=PeriodoAcademico.objects.order_by('-fecha_inicio'),
        empty_label='Todos los periodos',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
    rol = forms.ModelChoiceField(
        required=False,
        label='Rol de usuario',
        queryset=Rol.objects.filter(estado=Estado.ACTIVO).order_by('nombre'),
        empty_label='Todos los roles',
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )