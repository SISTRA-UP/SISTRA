"""Estudiantes, directores y sus inscripciones o asignaciones por carrera.

Tablas del diccionario de datos (docs/database/01_diccionario_de_datos.md,
sección 3): estudiante, director, estudiante_carrera y director_carrera.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class EstadoInscripcion(models.TextChoices):
    ACTIVO = 'Activo', 'Activo'
    INACTIVO = 'Inactivo', 'Inactivo'
    FINALIZADO = 'Finalizado', 'Finalizado'


class Estudiante(models.Model):
    id_estudiante = models.BigAutoField(primary_key=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario',
        related_name='estudiante',
    )

    class Meta:
        db_table = 'estudiante'
        verbose_name = 'estudiante'
        verbose_name_plural = 'estudiantes'

    def __str__(self):
        return str(self.usuario)


class Director(models.Model):
    id_director = models.BigAutoField(primary_key=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario',
        related_name='director',
    )

    class Meta:
        db_table = 'director'
        verbose_name = 'director'
        verbose_name_plural = 'directores'

    def __str__(self):
        return str(self.usuario)


class EstudianteCarrera(models.Model):
    """Inscripción de un estudiante en una carrera. Se conserva como historial
    aunque el estudiante deje o termine la carrera."""

    id_estudiante_carrera = models.BigAutoField(primary_key=True)
    # El índice lo cubre la restricción única (estudiante, carrera).
    estudiante = models.ForeignKey(
        Estudiante,
        on_delete=models.PROTECT,
        db_column='id_estudiante',
        db_index=False,
        related_name='inscripciones',
    )
    carrera = models.ForeignKey(
        'parametrizacion.Carrera',
        on_delete=models.PROTECT,
        db_column='id_carrera',
        related_name='inscripciones',
    )
    fecha_registro = models.DateField(default=timezone.localdate)
    estado = models.CharField(max_length=15, choices=EstadoInscripcion)
    fecha_finalizacion = models.DateField(blank=True, null=True)

    class Meta:
        db_table = 'estudiante_carrera'
        verbose_name = 'inscripción en carrera'
        verbose_name_plural = 'inscripciones en carrera'
        constraints = [
            models.UniqueConstraint(
                fields=['estudiante', 'carrera'], name='estudiante_carrera_unica'
            ),
            models.CheckConstraint(
                condition=Q(estado__in=EstadoInscripcion.values),
                name='estudiante_carrera_estado_valido',
            ),
            models.CheckConstraint(
                condition=Q(fecha_finalizacion__isnull=True)
                | Q(fecha_finalizacion__gte=F('fecha_registro')),
                name='estudiante_carrera_fechas_en_orden',
            ),
        ]

    def __str__(self):
        return f'{self.estudiante} · {self.carrera}'


class DirectorCarrera(models.Model):
    """Asignación de un Director a una carrera. Cada asignación se conserva
    como registro histórico; solo puede haber un Director activo por carrera."""

    id_director_carrera = models.BigAutoField(primary_key=True)
    director = models.ForeignKey(
        Director,
        on_delete=models.PROTECT,
        db_column='id_director',
        related_name='asignaciones',
    )
    # El índice lo cubre director_carrera_activo_idx (carrera, activo).
    carrera = models.ForeignKey(
        'parametrizacion.Carrera',
        on_delete=models.PROTECT,
        db_column='id_carrera',
        db_index=False,
        related_name='asignaciones_director',
    )
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = 'director_carrera'
        verbose_name = 'asignación de director'
        verbose_name_plural = 'asignaciones de director'
        constraints = [
            models.UniqueConstraint(
                fields=['carrera'],
                condition=Q(activo=True),
                name='director_carrera_un_activo',
            ),
            models.CheckConstraint(
                condition=Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=F('fecha_inicio')),
                name='director_carrera_fechas_en_orden',
            ),
        ]
        indexes = [
            models.Index(fields=['carrera', 'activo'], name='director_carrera_activo_idx'),
        ]

    def __str__(self):
        return f'{self.director} · {self.carrera}'
