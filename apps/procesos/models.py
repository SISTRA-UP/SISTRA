"""Proceso de Trabajo Social de cada inscripción estudiante-carrera.

Tablas del diccionario de datos (docs/database/01_diccionario_de_datos.md,
sección 4): proceso_trabajo_social y proceso_actividad.

El proceso se crea cuando el Director registra al estudiante en una carrera
(SISTRA-10). La usan SISTRA-01, 06 y 14; no tiene pantallas propias.
"""

from django.db import models
from django.db.models import F, Q


class EstadoAvance(models.TextChoices):
    PENDIENTE = 'Pendiente', 'Pendiente'
    EN_CURSO = 'En curso', 'En curso'
    FINALIZADA = 'Finalizada', 'Finalizada'


class ProcesoTrabajoSocial(models.Model):
    """Trabajo Social de un estudiante en una carrera. Agrupa sus propuestas
    (y, a través de ellas, sus informes) y su avance por etapas."""

    id_proceso = models.BigAutoField(primary_key=True)
    estudiante_carrera = models.OneToOneField(
        'personas.EstudianteCarrera',
        on_delete=models.PROTECT,
        db_column='id_estudiante_carrera',
        related_name='proceso',
    )
    fecha_inicio = models.DateTimeField()
    fecha_finalizacion = models.DateTimeField(blank=True, null=True)
    estado = models.CharField(max_length=20, choices=EstadoAvance)

    class Meta:
        db_table = 'proceso_trabajo_social'
        verbose_name = 'proceso de Trabajo Social'
        verbose_name_plural = 'procesos de Trabajo Social'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoAvance.values), name='proceso_estado_valido'
            ),
            models.CheckConstraint(
                condition=Q(fecha_finalizacion__isnull=True)
                | Q(fecha_finalizacion__gte=F('fecha_inicio')),
                name='proceso_fechas_en_orden',
            ),
        ]

    def __str__(self):
        return f'Proceso {self.pk} · {self.estudiante_carrera}'


class ProcesoActividad(models.Model):
    """Avance de un proceso en cada etapa del catálogo `actividad`."""

    id_proceso_actividad = models.BigAutoField(primary_key=True)
    # El índice lo cubre la restricción única (proceso, actividad).
    proceso = models.ForeignKey(
        ProcesoTrabajoSocial,
        on_delete=models.PROTECT,
        db_column='id_proceso',
        db_index=False,
        related_name='etapas',
    )
    actividad = models.ForeignKey(
        'parametrizacion.Actividad',
        on_delete=models.PROTECT,
        db_column='id_actividad',
        related_name='avances',
    )
    estado = models.CharField(max_length=20, choices=EstadoAvance)
    fecha_inicio = models.DateTimeField(blank=True, null=True)
    fecha_finalizacion = models.DateTimeField(blank=True, null=True)
    observacion = models.TextField(blank=True)

    class Meta:
        db_table = 'proceso_actividad'
        verbose_name = 'etapa del proceso'
        verbose_name_plural = 'etapas del proceso'
        constraints = [
            models.UniqueConstraint(
                fields=['proceso', 'actividad'], name='proceso_actividad_unica'
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoAvance.values),
                name='proceso_actividad_estado_valido',
            ),
            models.CheckConstraint(
                condition=Q(fecha_inicio__isnull=True)
                | Q(fecha_finalizacion__isnull=True)
                | Q(fecha_finalizacion__gte=F('fecha_inicio')),
                name='proceso_actividad_fechas_en_orden',
            ),
        ]

    def __str__(self):
        return f'{self.proceso} · {self.actividad}'
