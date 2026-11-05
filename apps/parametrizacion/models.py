"""Estructura institucional, catálogos y configuración de SISTRA.

Tablas del diccionario de datos (docs/database/01_diccionario_de_datos.md,
secciones 1 y 8): facultad, carrera, periodo_academico, actividad,
tipo_rechazo, parametro, plantilla y version_plantilla.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.usuarios.models import Estado


class EstadoPeriodo(models.TextChoices):
    VIGENTE = 'Vigente', 'Vigente'
    CERRADO = 'Cerrado', 'Cerrado'


class Facultad(models.Model):
    id_facultad = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=15, choices=Estado, default=Estado.ACTIVO)

    class Meta:
        db_table = 'facultad'
        verbose_name = 'facultad'
        verbose_name_plural = 'facultades'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=Estado.values), name='facultad_estado_valido'
            ),
        ]

    def __str__(self):
        return self.nombre


class Carrera(models.Model):
    id_carrera = models.BigAutoField(primary_key=True)
    facultad = models.ForeignKey(
        Facultad, on_delete=models.PROTECT, db_column='id_facultad', related_name='carreras'
    )
    nombre = models.CharField(max_length=120)
    codigo = models.CharField(max_length=20, unique=True)
    estado = models.CharField(max_length=15, choices=Estado, default=Estado.ACTIVO)

    class Meta:
        db_table = 'carrera'
        verbose_name = 'carrera'
        verbose_name_plural = 'carreras'
        constraints = [
            models.UniqueConstraint(
                fields=['facultad', 'nombre'], name='carrera_nombre_unico_por_facultad'
            ),
            models.CheckConstraint(
                condition=Q(estado__in=Estado.values), name='carrera_estado_valido'
            ),
        ]

    def __str__(self):
        return self.nombre


class PeriodoAcademico(models.Model):
    id_periodo_academico = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=20, unique=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    fecha_cierre_propuesta = models.DateField()
    fecha_cierre_informe = models.DateField()
    estado = models.CharField(max_length=15, choices=EstadoPeriodo)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'periodo_academico'
        verbose_name = 'periodo académico'
        verbose_name_plural = 'periodos académicos'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoPeriodo.values), name='periodo_estado_valido'
            ),
            models.CheckConstraint(
                condition=Q(fecha_fin__gte=F('fecha_inicio')), name='periodo_fechas_en_orden'
            ),
            # BRD SISTRA-11: el cierre de propuesta va dentro del periodo y el
            # cierre de informe es posterior al cierre de propuesta.
            models.CheckConstraint(
                condition=Q(fecha_cierre_propuesta__gte=F('fecha_inicio'))
                & Q(fecha_cierre_propuesta__lte=F('fecha_fin')),
                name='periodo_cierre_propuesta_en_periodo',
            ),
            models.CheckConstraint(
                condition=Q(fecha_cierre_informe__gt=F('fecha_cierre_propuesta')),
                name='periodo_cierre_informe_posterior',
            ),
            # Un solo periodo Vigente a la vez (BRD RN-11-02).
            models.UniqueConstraint(
                fields=['estado'],
                condition=Q(estado=EstadoPeriodo.VIGENTE),
                name='periodo_un_solo_vigente',
            ),
        ]

    def __str__(self):
        return self.nombre


class Actividad(models.Model):
    """Catálogo de etapas generales del proceso de Trabajo Social.

    La cantidad, nombres y orden de las etapas están pendientes de
    confirmación de la profesora.
    """

    id_actividad = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    orden = models.SmallIntegerField(unique=True)
    obligatoria = models.BooleanField()
    estado = models.CharField(max_length=15, choices=Estado)

    class Meta:
        db_table = 'actividad'
        verbose_name = 'actividad'
        verbose_name_plural = 'actividades'
        ordering = ['orden']
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=Estado.values), name='actividad_estado_valido'
            ),
        ]

    def __str__(self):
        return self.nombre


class TipoRechazo(models.Model):
    """Catálogo de tipos de rechazo de propuestas e informes (valores pendientes)."""

    id_tipo_rechazo = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=15, choices=Estado)

    class Meta:
        db_table = 'tipo_rechazo'
        verbose_name = 'tipo de rechazo'
        verbose_name_plural = 'tipos de rechazo'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=Estado.values), name='tipo_rechazo_estado_valido'
            ),
        ]

    def __str__(self):
        return self.nombre


class Parametro(models.Model):
    """Valores configurables por el Administrador (semáforo, recordatorios,
    URL de UP, formatos, tamaños, límites de CSV, plazos de archivado...)."""

    id_parametro = models.BigAutoField(primary_key=True)
    clave = models.CharField(max_length=100, unique=True)
    valor = models.TextField()
    descripcion = models.TextField(blank=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    usuario_actualizacion = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario_actualizacion',
        related_name='parametros_actualizados',
    )

    class Meta:
        db_table = 'parametro'
        verbose_name = 'parámetro'
        verbose_name_plural = 'parámetros'

    def __str__(self):
        return self.clave


class Plantilla(models.Model):
    """Plantillas descargables: Word de propuesta y CSV de registro de estudiantes."""

    id_plantilla = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=30)
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=15)

    class Meta:
        db_table = 'plantilla'
        verbose_name = 'plantilla'
        verbose_name_plural = 'plantillas'

    def __str__(self):
        return self.nombre


class VersionPlantilla(models.Model):
    id_version_plantilla = models.BigAutoField(primary_key=True)
    plantilla = models.ForeignKey(
        Plantilla, on_delete=models.PROTECT, db_column='id_plantilla', related_name='versiones'
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario',
        related_name='versiones_plantilla_cargadas',
    )
    numero_version = models.IntegerField()
    nombre_archivo = models.CharField(max_length=200)
    ruta_archivo = models.TextField()
    fecha_carga = models.DateTimeField(default=timezone.now)
    es_vigente = models.BooleanField()

    class Meta:
        db_table = 'version_plantilla'
        verbose_name = 'versión de plantilla'
        verbose_name_plural = 'versiones de plantilla'
        constraints = [
            models.UniqueConstraint(
                fields=['plantilla', 'numero_version'], name='version_plantilla_numero_unico'
            ),
            models.UniqueConstraint(
                fields=['plantilla'],
                condition=Q(es_vigente=True),
                name='version_plantilla_una_vigente',
            ),
        ]

    def __str__(self):
        return f'{self.plantilla} v{self.numero_version}'
