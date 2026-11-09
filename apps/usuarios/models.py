"""Usuarios, roles y permisos de SISTRA (tablas usuario, rol, permiso y
rol_permiso del DER).

Se inicia sesión con `correo_institucional` y contraseña. La contraseña se
guarda siempre como hash (columna `contrasena_hash`), nunca en texto plano.

En el resto del proyecto nunca se importa `Usuario` directamente:

- En modelos:  models.ForeignKey(settings.AUTH_USER_MODEL, ...)
- En código:   from django.contrib.auth import get_user_model
"""

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings

ROL_ADMINISTRADOR = 'Administrador'
ROL_ESTUDIANTE = 'Estudiante'
ROL_DIRECTOR = 'Director'
PERMISO_PARAMETRIZAR = 'parametrizar_sistema'
PERMISO_CREAR_USUARIOS = 'crear_usuarios'





class Estado(models.TextChoices):
    ACTIVO = 'Activo', 'Activo'
    INACTIVO = 'Inactivo', 'Inactivo'


class Rol(models.Model):
    id_rol = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=30, unique=True)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.ACTIVO)

    class Meta:
        db_table = 'rol'
        verbose_name = 'rol'
        verbose_name_plural = 'roles'

    def __str__(self):
        return self.nombre


class Permiso(models.Model):
    id_permiso = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=80, unique=True)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.ACTIVO)

    class Meta:
        db_table = 'permiso'
        verbose_name = 'permiso'
        verbose_name_plural = 'permisos'

    def __str__(self):
        return self.nombre


class RolPermiso(models.Model):
    pk = models.CompositePrimaryKey('rol', 'permiso')
    rol = models.ForeignKey(
        Rol, on_delete=models.CASCADE, db_column='id_rol', related_name='asignaciones'
    )
    permiso = models.ForeignKey(
        Permiso, on_delete=models.CASCADE, db_column='id_permiso', related_name='asignaciones'
    )

    class Meta:
        db_table = 'rol_permiso'
        verbose_name = 'permiso del rol'
        verbose_name_plural = 'permisos del rol'


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        return (email or '').strip().lower()

    def get_by_natural_key(self, correo):
        # Lo usa el login: ignora mayúsculas en lo que escribe el usuario.
        return self.get(correo_institucional__iexact=correo)

    def create_user(self, correo_institucional, password=None, **campos):
        """Crea un usuario guardando la contraseña como hash."""
        if not correo_institucional:
            raise ValueError('El correo institucional es obligatorio.')
        usuario = self.model(
            correo_institucional=self.normalize_email(correo_institucional), **campos
        )
        usuario.set_password(password)
        usuario.full_clean()
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, correo_institucional, password=None, **campos):
        """Lo usa `manage.py createsuperuser`: crea el administrador del sistema."""
        with transaction.atomic(using=self._db):
            rol, _ = Rol.objects.using(self._db).get_or_create(nombre=ROL_ADMINISTRADOR)
            campos.setdefault('rol', rol)
            # Él mismo eligió la contraseña en la terminal: no se le obliga a cambiarla.
            campos.setdefault('requiere_cambio_contrasena', False)
            return self.create_user(correo_institucional, password, **campos)


class Usuario(AbstractBaseUser):
    id_usuario = models.BigAutoField(primary_key=True)
    rol = models.ForeignKey(
        Rol, on_delete=models.PROTECT, db_column='id_rol', related_name='usuarios'
    )
    nombre = models.CharField(max_length=120)
    cedula = models.CharField(max_length=15, unique=True)
    correo_institucional = models.EmailField(max_length=254, unique=True)
    nombre_usuario = models.CharField(max_length=80, unique=True)
    telefono = models.CharField(max_length=20, blank=True, default='')
    # Heredados de AbstractBaseUser, con los nombres de columna del DER.
    password = models.CharField('contraseña', max_length=255, db_column='contrasena_hash')
    last_login = models.DateTimeField('último ingreso', blank=True, null=True, db_column='ultimo_ingreso')
    requiere_cambio_contrasena = models.BooleanField(default=True)
    estado = models.CharField(max_length=10, choices=Estado, default=Estado.ACTIVO)
    intentos_fallidos = models.PositiveIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)

    USERNAME_FIELD = 'correo_institucional'
    EMAIL_FIELD = 'correo_institucional'
    REQUIRED_FIELDS = ['nombre', 'cedula', 'nombre_usuario']

    objects = UsuarioManager()

    class Meta:
        db_table = 'usuario'
        verbose_name = 'usuario'
        verbose_name_plural = 'usuarios'

    def __str__(self):
        return f'{self.nombre} <{self.correo_institucional}>'

    def clean(self):
        super().clean()
        self.correo_institucional = type(self).objects.normalize_email(self.correo_institucional)

    # --- Lo que Django consulta para el login y los permisos ---

    @property
    def is_active(self):
        # El login de Django rechaza a los usuarios con is_active=False.
        return self.estado == Estado.ACTIVO

    @property
    def es_administrador(self):
        return self.rol.nombre == ROL_ADMINISTRADOR

    def _nombres_permisos(self):
        if not hasattr(self, '_cache_permisos'):
            if self.rol.estado != Estado.ACTIVO:
                self._cache_permisos = set()
            else:
                self._cache_permisos = set(
                    Permiso.objects.filter(
                        asignaciones__rol_id=self.rol_id, estado=Estado.ACTIVO
                    ).values_list('nombre', flat=True)
                )
        return self._cache_permisos

    def has_perm(self, perm, obj=None):
        """Permite usar @permission_required('nombre_del_permiso') en las vistas."""
        return self.is_active and perm in self._nombres_permisos()

    def has_perms(self, perm_list, obj=None):
        return all(self.has_perm(perm, obj) for perm in perm_list)



class ResultadoFila(models.TextChoices):
    CREADA = 'Creada', 'Creada'
    ACTUALIZADA = 'Actualizada', 'Actualizada'
    ERROR = 'Error', 'Error'



class CargaMasiva(models.Model):
    """Una subida de CSV: quién la hizo, cuándo y los totales."""
    id_carga_masiva = models.BigAutoField(primary_key=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        db_column='id_usuario', related_name='cargas_masivas',
    )
    nombre_archivo = models.CharField(max_length=200)
    fecha_carga = models.DateTimeField(default=timezone.now, editable=False)
    total_filas = models.PositiveIntegerField(default=0)
    creadas = models.PositiveIntegerField(default=0)
    actualizadas = models.PositiveIntegerField(default=0)
    con_error = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'carga_masiva'
        verbose_name = 'carga masiva'
        verbose_name_plural = 'cargas masivas'




class CargaMasivaFila(models.Model):
    """Resultado de cada fila; es la base del log descargable."""
    id_carga_masiva_fila = models.BigAutoField(primary_key=True)
    carga = models.ForeignKey(
        CargaMasiva, on_delete=models.CASCADE,
        db_column='id_carga_masiva', related_name='filas',
    )
    numero_fila = models.PositiveIntegerField()
    cedula = models.CharField(max_length=40, blank=True)
    correo_institucional = models.CharField(max_length=254, blank=True)
    resultado = models.CharField(max_length=15, choices=ResultadoFila)
    detalle = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'carga_masiva_fila'
        constraints = [
            models.UniqueConstraint(
                fields=['carga', 'numero_fila'], name='carga_masiva_fila_unica'
            ),
        ]


