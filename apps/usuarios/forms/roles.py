"""SISTRA-10 · Roles (roles, permisos y usuarios): formularios.

Solo el responsable de este requisito edita este archivo.
"""

from django import forms
from django.db import transaction

from apps.usuarios.models import ROL_ADMINISTRADOR, Estado, Permiso, Rol, RolPermiso

# Los tres roles que exige la regla de negocio §3.6 (RG-01). No se renombran ni
# se inactivan: el sistema los da por existentes.
ROLES_BASE = ('Estudiante', 'Director', ROL_ADMINISTRADOR)


class RolForm(forms.ModelForm):
    """Crea o edita un rol y, de paso, los permisos que tiene.

    `rol_permiso` no es un ManyToMany declarado en el modelo (tiene clave
    primaria compuesta), así que las filas se sincronizan a mano en `save()`.
    El campo de permisos solo aparece si quien edita tiene
    `rol.asignar_permisos`.

    `estado` no es un campo de este formulario a propósito: se cambia solo por
    la vista `cambiar_estado_rol`, que exige `rol.inactivar`. Si estuviera aquí,
    cualquiera con `rol.editar` podría inactivar un rol sin ese permiso.
    """

    permisos = forms.ModelMultipleChoiceField(
        queryset=Permiso.objects.filter(estado=Estado.ACTIVO).order_by('nombre'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label='Permisos del rol',
        help_text='Lo que podrá hacer quien tenga este rol.',
    )

    class Meta:
        model = Rol
        fields = ['nombre', 'descripcion']
        labels = {
            'nombre': 'Nombre del rol',
            'descripcion': 'Descripción',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, puede_asignar_permisos=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._nombre_original = self.instance.nombre if self.instance.pk else None
        if not puede_asignar_permisos:
            del self.fields['permisos']
        elif self.instance.pk:
            self.fields['permisos'].initial = list(
                Permiso.objects.filter(asignaciones__rol=self.instance).values_list(
                    'id_permiso', flat=True
                )
            )

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre']
        if self._nombre_original in ROLES_BASE and nombre != self._nombre_original:
            raise forms.ValidationError(
                f'{self._nombre_original} es un rol base del sistema: no se le puede '
                f'cambiar el nombre.'
            )
        return nombre

    @transaction.atomic
    def save(self, commit=True):
        rol = super().save(commit=commit)
        if commit and 'permisos' in self.cleaned_data:
            self._sincronizar_permisos(rol)
        return rol

    def _sincronizar_permisos(self, rol):
        elegidos = {permiso.pk for permiso in self.cleaned_data['permisos']}
        actuales = set(
            RolPermiso.objects.filter(rol=rol).values_list('permiso_id', flat=True)
        )
        RolPermiso.objects.filter(rol=rol, permiso_id__in=actuales - elegidos).delete()
        for id_permiso in elegidos - actuales:
            RolPermiso.objects.create(rol=rol, permiso_id=id_permiso)


class BusquedaUsuarioForm(forms.Form):
    """Un solo cuadro de texto y el filtro por rol.

    `q` busca en nombre, cédula, nombre de usuario y correo del usuario, y
    también en el nombre y el código de las carreras en que esté inscrito.
    """

    q = forms.CharField(
        required=False,
        label='Buscar',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Nombre, cédula, usuario, correo o carrera',
            }
        ),
    )
    rol = forms.ModelChoiceField(
        queryset=Rol.objects.order_by('nombre'),
        required=False,
        empty_label='Todos los roles',
        label='Rol',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
