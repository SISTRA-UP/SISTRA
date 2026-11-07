"""SISTRA-10 · Roles (roles, permisos y usuarios): formularios.

Solo el responsable de este requisito edita este archivo.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.parametrizacion.models import Carrera
from apps.personas.models import Director, DirectorCarrera
from apps.usuarios.models import ROL_ADMINISTRADOR, Estado, Permiso, Rol, RolPermiso

Usuario = get_user_model()

ROL_DIRECTOR = 'Director'

# Los tres roles que exige la regla de negocio §3.6 (RG-01). No se renombran ni
# se inactivan: el sistema los da por existentes.
ROLES_BASE = ('Estudiante', 'Director', ROL_ADMINISTRADOR)

# Lo mínimo que el rol Administrador tiene que conservar para poder deshacer un
# cambio de permisos. Sin `rol.ver` no se llega a la lista; sin `rol.editar` no
# se abre el formulario; sin `rol.asignar_permisos` el formulario no muestra las
# casillas. Si se queda sin los tres, no hay salida por ninguna pantalla: el
# panel /admin/ está desactivado, `Usuario.has_perm()` no tiene atajo de
# superusuario, y `createsuperuser` no rescata porque reutiliza este mismo rol.
PERMISOS_MINIMOS_DEL_ADMINISTRADOR = ('rol.ver', 'rol.editar', 'rol.asignar_permisos')


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
        # Los llena `_sincronizar_permisos` para que la vista los audite.
        self.permisos_agregados = []
        self.permisos_quitados = []
        self._nombre_original = self.instance.nombre if self.instance.pk else None
        if not puede_asignar_permisos:
            del self.fields['permisos']
        elif self.instance.pk:
            self.fields['permisos'].initial = list(
                Permiso.objects.filter(asignaciones__rol=self.instance).values_list(
                    'id_permiso', flat=True
                )
            )

    def clean_permisos(self):
        """Evita que el rol Administrador se quede sin cómo deshacer el cambio."""
        elegidos = self.cleaned_data['permisos']
        if self._nombre_original != ROL_ADMINISTRADOR:
            return elegidos
        nombres = {permiso.nombre for permiso in elegidos}
        faltan = [
            nombre
            for nombre in PERMISOS_MINIMOS_DEL_ADMINISTRADOR
            if nombre not in nombres
        ]
        if faltan:
            raise forms.ValidationError(
                f'El rol {ROL_ADMINISTRADOR} no se puede quedar sin '
                f'{", ".join(faltan)}: sin esos permisos nadie podría volver a esta '
                f'pantalla para deshacerlo, y crear un superusuario tampoco serviría, '
                f'porque reutiliza este mismo rol.'
            )
        return elegidos

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
        quitados, agregados = actuales - elegidos, elegidos - actuales
        self.permisos_quitados = sorted(
            Permiso.objects.filter(pk__in=quitados).values_list('nombre', flat=True)
        )
        self.permisos_agregados = sorted(
            Permiso.objects.filter(pk__in=agregados).values_list('nombre', flat=True)
        )
        RolPermiso.objects.filter(rol=rol, permiso_id__in=quitados).delete()
        for id_permiso in agregados:
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


class UsuarioForm(forms.ModelForm):
    """Crea o edita un usuario y, si su rol es Director, su carrera.

    Tres campos quedan fuera a propósito:

    - `estado`: se cambia solo por `cambiar_estado_usuario`, que exige
      `usuario.inactivar`. Si estuviera aquí, cualquiera con `usuario.editar`
      podría inactivar a alguien sin ese permiso.
    - la contraseña: al crear se genera una **temporal aleatoria** y el usuario
      queda con `requiere_cambio_contrasena`. No se muestra en pantalla ni se
      envía desde aquí; entregarla es el correo de SIS-19 (RG-09), y cambiarla
      en el primer ingreso es SISTRA-13 (RN-10-06).
    - `nombre_usuario`: es la parte del correo anterior a la `@` (nota técnica
      del BRD §5.11), así que se deriva y no se pide.

    Al crear, el formulario **siempre guarda**: necesita el id del usuario para
    poder colgarle la asignación de carrera.
    """

    carrera = forms.ModelChoiceField(
        queryset=Carrera.objects.filter(estado=Estado.ACTIVO).order_by('nombre'),
        required=False,
        label='Carrera',
        empty_label='— ninguna —',
        help_text='Obligatoria si el rol es Director: solo puede haber un Director activo por carrera.',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = Usuario
        fields = ['nombre', 'cedula', 'correo_institucional', 'rol']
        labels = {
            'nombre': 'Nombre completo',
            'cedula': 'Cédula',
            'correo_institucional': 'Correo institucional',
            'rol': 'Rol',
        }
        help_texts = {
            'correo_institucional': 'Con este correo entra al sistema (RG-14).',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
            'cedula': forms.TextInput(attrs={'class': 'form-control', 'inputmode': 'numeric'}),
            'correo_institucional': forms.EmailInput(attrs={'class': 'form-control'}),
            'rol': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, es_su_propia_cuenta=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.es_su_propia_cuenta = es_su_propia_cuenta
        # Lo llena `_sincronizar_carrera` para que la vista lo audite: `carrera`
        # no es campo del modelo `Usuario`, así que no aparece en `self.initial`
        # y el valor anterior se perdería.
        self.cambio_de_carrera = ''
        # Un rol inactivo deja sin permisos a sus usuarios, así que no se ofrece;
        # el que ya tenga el usuario sí se conserva, para no romper la edición.
        self.fields['rol'].queryset = Rol.objects.filter(
            Q(estado=Estado.ACTIVO) | Q(pk=self.instance.rol_id)
        ).order_by('nombre')
        asignacion = self.asignacion_activa(self.instance) if self.instance.pk else None
        self._carrera_original = asignacion.carrera if asignacion else None
        if asignacion:
            self.fields['carrera'].initial = asignacion.carrera_id
            # Mismo criterio que con el rol: si SISTRA-11 inactiva la carrera,
            # su Director tiene que seguir siendo editable.
            self.fields['carrera'].queryset = Carrera.objects.filter(
                Q(estado=Estado.ACTIVO) | Q(pk=asignacion.carrera_id)
            ).order_by('nombre')
        if es_su_propia_cuenta:
            # Misma idea que "no puedes inactivar tu propia cuenta": si el único
            # Administrador se cambia el rol, se queda sin poder entrar a nada.
            self.fields['rol'].disabled = True
            self.fields['rol'].help_text = 'No puedes cambiarte el rol a ti mismo.'

    @staticmethod
    def asignacion_activa(usuario):
        """La asignación de carrera vigente del usuario, si es Director."""
        director = Director.objects.filter(usuario=usuario).first()
        if director is None:
            return None
        return (
            DirectorCarrera.objects.filter(director=director, activo=True)
            .select_related('carrera')
            .first()
        )

    def clean(self):
        datos = super().clean()
        rol, carrera = datos.get('rol'), datos.get('carrera')
        if rol is None:
            return datos

        if rol.nombre != ROL_DIRECTOR:
            if carrera:
                self.add_error('carrera', 'La carrera solo se le asigna a un Director.')
            return datos

        if not carrera:
            self.add_error('carrera', 'Un Director necesita la carrera que va a dirigir.')
            return datos

        ocupada = DirectorCarrera.objects.filter(carrera=carrera, activo=True)
        if self.instance.pk:
            ocupada = ocupada.exclude(director__usuario=self.instance)
        otra = ocupada.select_related('director__usuario').first()
        if otra:
            self.add_error(
                'carrera',
                f'{carrera.nombre} ya tiene un Director activo: {otra.director.usuario.nombre}. '
                f'Cámbiale primero el rol o la carrera.',
            )
        return datos

    @transaction.atomic
    def save(self, commit=True):
        if self.instance.pk:
            if 'correo_institucional' in self.changed_data:
                # El contrato dice que `nombre_usuario` es la parte anterior a
                # la @: si cambia el correo, se vuelve a derivar o quedaría
                # contradiciendo al correo en la misma pantalla.
                self.instance.nombre_usuario = self._nombre_usuario_libre(
                    self.cleaned_data['correo_institucional'], excluir=self.instance.pk
                )
            usuario = super().save(commit=commit)
        else:
            usuario = Usuario.objects.create_user(
                correo_institucional=self.cleaned_data['correo_institucional'],
                # Temporal y aleatoria: nadie la ve, se reemplaza en el primer ingreso.
                password=get_random_string(16),
                nombre=self.cleaned_data['nombre'],
                cedula=self.cleaned_data['cedula'],
                nombre_usuario=self._nombre_usuario_libre(
                    self.cleaned_data['correo_institucional']
                ),
                rol=self.cleaned_data['rol'],
                requiere_cambio_contrasena=True,
            )
            self.instance = usuario
            commit = True
        if commit:
            self._sincronizar_carrera(usuario)
        return usuario

    @staticmethod
    def _nombre_usuario_libre(correo, excluir=None):
        """La parte anterior a la `@`, y si ya está tomada le añade un número.

        `excluir` es el id del usuario que se está editando: si no se excluyera,
        su propio nombre de usuario contaría como ocupado y se le pondría un
        número sin motivo.
        """
        base = (correo.split('@')[0] or 'usuario').strip().lower()[:80]
        tomados = Usuario.objects.all()
        if excluir is not None:
            tomados = tomados.exclude(pk=excluir)
        candidato, siguiente = base, 2
        while tomados.filter(nombre_usuario=candidato).exists():
            sufijo = f'-{siguiente}'
            candidato = f'{base[: 80 - len(sufijo)]}{sufijo}'
            siguiente += 1
        return candidato

    def _sincronizar_carrera(self, usuario):
        """Deja `director` y `director_carrera` de acuerdo con el rol.

        Las asignaciones no se borran: se cierran con `activo=False` y
        `fecha_fin`, porque son historial (regla §17 y el propio docstring de
        `DirectorCarrera`).
        """
        es_director = usuario.rol.nombre == ROL_DIRECTOR
        director = Director.objects.filter(usuario=usuario).first()
        antes = self._carrera_original.nombre if self._carrera_original else '—'

        if not es_director:
            if director is not None and DirectorCarrera.objects.filter(
                director=director, activo=True
            ).exists():
                self._cerrar_asignaciones(director)
                self.cambio_de_carrera = f'carrera: {antes} → — (asignación cerrada)'
            return

        carrera = self.cleaned_data['carrera']
        if director is None:
            director = Director.objects.create(usuario=usuario)
        activa = DirectorCarrera.objects.filter(director=director, activo=True).first()
        if activa is not None:
            if activa.carrera_id == carrera.pk:
                return
            self._cerrar_asignaciones(director)
        self.cambio_de_carrera = f'carrera: {antes} → {carrera.nombre}'
        DirectorCarrera.objects.create(
            director=director,
            carrera=carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )

    @staticmethod
    def _cerrar_asignaciones(director):
        DirectorCarrera.objects.filter(director=director, activo=True).update(
            activo=False, fecha_fin=timezone.localdate()
        )
