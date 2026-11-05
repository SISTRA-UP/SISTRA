"""Informes de Trabajo Social.

Tabla del diccionario de datos (docs/database/01_diccionario_de_datos.md,
sección 5.2): informe. Usa los mismos 7 estados de la propuesta.
"""

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.propuestas.models import EstadoTramite


class Informe(models.Model):
    """Informe de Trabajo Social; solo se diligencia por formulario.

    Un informe nuevo empieza en la versión de entrega 1; cada corrección y
    reenvío del mismo informe la incrementa.
    """

    id_informe = models.BigAutoField(primary_key=True)
    # El índice lo cubre informe_propuesta_estado_idx (propuesta, estado).
    propuesta = models.ForeignKey(
        'propuestas.Propuesta',
        on_delete=models.PROTECT,
        db_column='id_propuesta',
        db_index=False,
        related_name='informes',
    )
    # Periodo de creación: no cambia al reenviar.
    periodo_academico = models.ForeignKey(
        'parametrizacion.PeriodoAcademico',
        on_delete=models.PROTECT,
        db_column='id_periodo_academico',
        related_name='informes',
    )
    codigo = models.CharField(max_length=30, unique=True)
    resultados = models.TextField(blank=True)
    conclusiones = models.TextField(blank=True)
    recomendaciones = models.TextField(blank=True)
    estado = models.CharField(
        max_length=30, choices=EstadoTramite, default=EstadoTramite.BORRADOR
    )
    version_entrega = models.IntegerField(default=1)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    fecha_envio = models.DateTimeField(blank=True, null=True)
    archivado = models.BooleanField(default=False)
    fecha_archivado = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'informe'
        verbose_name = 'informe'
        verbose_name_plural = 'informes'
        constraints = [
            models.CheckConstraint(
                condition=Q(estado__in=EstadoTramite.values), name='informe_estado_valido'
            ),
            models.CheckConstraint(
                condition=Q(version_entrega__gt=0), name='informe_version_entrega_positiva'
            ),
            # Un solo informe activo por propuesta: activo = no archivado y en
            # un estado distinto de Rechazado.
            models.UniqueConstraint(
                fields=['propuesta'],
                condition=Q(archivado=False) & ~Q(estado=EstadoTramite.RECHAZADO),
                name='informe_uno_activo_por_propuesta',
            ),
        ]
        indexes = [
            models.Index(fields=['propuesta', 'estado'], name='informe_propuesta_estado_idx'),
        ]

    def __str__(self):
        return self.codigo
