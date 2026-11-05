"""Cargues en la Plataforma UP y su verificación por el Director.

Tablas del diccionario de datos (docs/database/01_diccionario_de_datos.md,
secciones 6.2 y 6.3): cargue_up e historial_cargue_up.
"""

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class EstadoVerificacion(models.TextChoices):
    PENDIENTE = 'Pendiente', 'Pendiente'
    APROBADO_EN_UP = 'Aprobado en UP', 'Aprobado en UP'
    RECHAZADO_EN_UP = 'Rechazado en UP', 'Rechazado en UP'


# Exactamente uno entre propuesta e informe.
SOLO_PROPUESTA_O_INFORME = (
    Q(propuesta__isnull=False, informe__isnull=True)
    | Q(propuesta__isnull=True, informe__isnull=False)
)


class CargueUp(models.Model):
    """Cada intento de carga del estudiante en UP (cada «Subido en UP») crea una fila."""

    id_cargue_up = models.BigAutoField(primary_key=True)
    propuesta = models.ForeignKey(
        'propuestas.Propuesta',
        on_delete=models.PROTECT,
        db_column='id_propuesta',
        blank=True,
        null=True,
        related_name='cargues_up',
    )
    informe = models.ForeignKey(
        'informes.Informe',
        on_delete=models.PROTECT,
        db_column='id_informe',
        blank=True,
        null=True,
        related_name='cargues_up',
    )
    # NULL hasta que el Director verifica.
    director = models.ForeignKey(
        'personas.Director',
        on_delete=models.PROTECT,
        db_column='id_director',
        blank=True,
        null=True,
        related_name='cargues_verificados',
    )
    fecha_declaracion = models.DateTimeField(default=timezone.now)
    estado_verificacion = models.CharField(
        max_length=25, choices=EstadoVerificacion, default=EstadoVerificacion.PENDIENTE
    )
    fecha_verificacion = models.DateTimeField(blank=True, null=True)
    observacion = models.TextField(blank=True)

    class Meta:
        db_table = 'cargue_up'
        verbose_name = 'cargue en UP'
        verbose_name_plural = 'cargues en UP'
        constraints = [
            models.CheckConstraint(
                condition=SOLO_PROPUESTA_O_INFORME, name='cargue_up_propuesta_o_informe'
            ),
            models.CheckConstraint(
                condition=Q(estado_verificacion__in=EstadoVerificacion.values),
                name='cargue_up_estado_valido',
            ),
            models.CheckConstraint(
                condition=Q(fecha_verificacion__isnull=True)
                | Q(fecha_verificacion__gte=F('fecha_declaracion')),
                name='cargue_up_verificacion_posterior',
            ),
            models.CheckConstraint(
                condition=~Q(estado_verificacion=EstadoVerificacion.RECHAZADO_EN_UP)
                | ~Q(observacion=''),
                name='cargue_up_rechazo_con_observacion',
            ),
        ]

    def __str__(self):
        tramite = self.propuesta or self.informe
        return f'Cargue {self.pk} · {tramite} · {self.estado_verificacion}'


class HistorialCargueUp(models.Model):
    """Conserva las correcciones de decisiones de UP sin sobrescribir la original.

    La corrección exige motivo (se valida en Django); si el resultado
    corregido es Rechazado en UP, también observación para el estudiante.
    """

    id_historial_cargue = models.BigAutoField(primary_key=True)
    cargue_up = models.ForeignKey(
        CargueUp,
        on_delete=models.PROTECT,
        db_column='id_cargue_up',
        related_name='historial',
    )
    director = models.ForeignKey(
        'personas.Director',
        on_delete=models.PROTECT,
        db_column='id_director',
        related_name='correcciones_cargue',
    )
    estado_anterior = models.CharField(
        max_length=25, choices=EstadoVerificacion, blank=True, null=True
    )
    estado_nuevo = models.CharField(max_length=25, choices=EstadoVerificacion)
    observacion = models.TextField(blank=True)
    motivo_correccion = models.TextField(blank=True)
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'historial_cargue_up'
        verbose_name = 'historial de cargue en UP'
        verbose_name_plural = 'historial de cargues en UP'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado_anterior__isnull=True)
                | Q(estado_anterior__in=EstadoVerificacion.values),
                name='historial_cargue_anterior_valido',
            ),
            models.CheckConstraint(
                condition=Q(estado_nuevo__in=EstadoVerificacion.values),
                name='historial_cargue_nuevo_valido',
            ),
            models.CheckConstraint(
                condition=~Q(estado_nuevo=EstadoVerificacion.RECHAZADO_EN_UP)
                | ~Q(observacion=''),
                name='historial_cargue_rechazo_con_observacion',
            ),
        ]

    def __str__(self):
        return f'{self.cargue_up} · {self.estado_anterior} → {self.estado_nuevo}'
