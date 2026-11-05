"""Propuestas de Trabajo Social y su cronograma de actividades.

Tablas del diccionario de datos (docs/database/01_diccionario_de_datos.md,
secciones 5.1 y 5.3): propuesta y actividad_cronograma.
"""

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class EstadoTramite(models.TextChoices):
    """Los 7 estados acordados para propuesta e informe.

    Archivada no es un estado: se representa con `archivada`/`archivado`
    y su fecha.
    """

    BORRADOR = 'Borrador', 'Borrador'
    EN_REVISION = 'En revisión', 'En revisión'
    REQUIERE_MODIFICACION = 'Requiere modificación', 'Requiere modificación'
    RECHAZADO = 'Rechazado', 'Rechazado'
    APROBADO = 'Aprobado', 'Aprobado'
    SUBIDO_EN_UP = 'Subido en UP', 'Subido en UP'
    APROBADO_EN_UP = 'Aprobado en UP', 'Aprobado en UP'


class SectorEntidad(models.TextChoices):
    PUBLICO = 'Público', 'Público'
    PRIVADO = 'Privado', 'Privado'


class Propuesta(models.Model):
    """Propuesta de Trabajo Social.

    Mientras está en Borrador puede tener campos sin diligenciar: los textos
    quedan vacíos y las fechas y el sector en NULL. Django valida que estén
    completos antes de enviar (avance al 100 %).
    """

    id_propuesta = models.BigAutoField(primary_key=True)
    # El índice lo cubre propuesta_proceso_estado_idx (proceso, estado).
    proceso = models.ForeignKey(
        'procesos.ProcesoTrabajoSocial',
        on_delete=models.PROTECT,
        db_column='id_proceso',
        db_index=False,
        related_name='propuestas',
    )
    # Periodo de creación: no cambia al reenviar.
    periodo_academico = models.ForeignKey(
        'parametrizacion.PeriodoAcademico',
        on_delete=models.PROTECT,
        db_column='id_periodo_academico',
        related_name='propuestas',
    )
    # Plantilla de Word usada; NULL si se diligenció en el formulario.
    version_plantilla = models.ForeignKey(
        'parametrizacion.VersionPlantilla',
        on_delete=models.PROTECT,
        db_column='id_version_plantilla',
        blank=True,
        null=True,
        related_name='propuestas',
    )
    codigo = models.CharField(max_length=30, unique=True)
    titulo = models.CharField(max_length=200, blank=True)
    resena_historica = models.TextField(blank=True)
    identificacion_necesidad = models.TextField(blank=True)
    justificacion = models.TextField(blank=True)
    objetivos = models.TextField(blank=True)
    referente_teorico = models.TextField(blank=True)
    impacto_social = models.TextField(blank=True)
    identificacion_poblacion = models.TextField(blank=True)
    propuesta_social = models.TextField(blank=True)
    entidad = models.CharField(max_length=200, blank=True)
    sector_entidad = models.CharField(
        max_length=20, choices=SectorEntidad, blank=True, null=True
    )
    poblacion_beneficiada = models.TextField(blank=True)
    zona = models.TextField(blank=True)
    area = models.TextField(blank=True)
    sector = models.TextField(blank=True)
    unidad = models.TextField(blank=True)
    fecha_inicio = models.DateField(blank=True, null=True)
    fecha_fin = models.DateField(blank=True, null=True)
    estado = models.CharField(
        max_length=30, choices=EstadoTramite, default=EstadoTramite.BORRADOR
    )
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    fecha_envio = models.DateTimeField(blank=True, null=True)
    archivada = models.BooleanField(default=False)
    fecha_archivado = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'propuesta'
        verbose_name = 'propuesta'
        verbose_name_plural = 'propuestas'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoTramite.values), name='propuesta_estado_valido'
            ),
            models.CheckConstraint(
                condition=Q(sector_entidad__isnull=True)
                | Q(sector_entidad__in=SectorEntidad.values),
                name='propuesta_sector_valido',
            ),
            models.CheckConstraint(
                condition=Q(fecha_inicio__isnull=True)
                | Q(fecha_fin__isnull=True)
                | Q(fecha_fin__gte=F('fecha_inicio')),
                name='propuesta_fechas_en_orden',
            ),
            # Una sola propuesta activa por proceso: activa = no archivada y
            # en un estado distinto de Rechazado.
            models.UniqueConstraint(
                fields=['proceso'],
                condition=Q(archivada=False) & ~Q(estado=EstadoTramite.RECHAZADO),
                name='propuesta_una_activa_por_proceso',
            ),
        ]
        indexes = [
            models.Index(fields=['proceso', 'estado'], name='propuesta_proceso_estado_idx'),
        ]

    def __str__(self):
        return f'{self.codigo} · {self.titulo}'


class ActividadCronograma(models.Model):
    """Actividad planificada dentro de una propuesta (no es una etapa del proceso)."""

    id_actividad_cronograma = models.BigAutoField(primary_key=True)
    # El índice lo cubre la restricción única (propuesta, orden).
    propuesta = models.ForeignKey(
        Propuesta,
        on_delete=models.PROTECT,
        db_column='id_propuesta',
        db_index=False,
        related_name='cronograma',
    )
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    orden = models.SmallIntegerField()
    responsable = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'actividad_cronograma'
        verbose_name = 'actividad del cronograma'
        verbose_name_plural = 'actividades del cronograma'
        ordering = ['propuesta', 'orden']
        constraints = [
            models.UniqueConstraint(
                fields=['propuesta', 'orden'], name='actividad_cronograma_orden_unico'
            ),
            models.CheckConstraint(
                condition=Q(fecha_fin__gte=F('fecha_inicio')),
                name='actividad_cronograma_fechas_en_orden',
            ),
        ]

    def __str__(self):
        return f'{self.orden}. {self.nombre}'
