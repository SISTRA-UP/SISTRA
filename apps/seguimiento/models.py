"""Historial de estados, notificaciones dentro de la plataforma y auditoría.

Tablas del diccionario de datos (docs/database/01_diccionario_de_datos.md,
secciones 6.1 y 7): historial_estado, notificacion y auditoria.

Es transversal: todos los requisitos escriben aquí. No tiene pantallas propias.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.propuestas.models import EstadoTramite


class HistorialEstado(models.Model):
    """Cada cambio de estado de una propuesta o de un informe, incluso en
    acciones masivas (una fila por trámite)."""

    id_historial = models.BigAutoField(primary_key=True)
    # Los índices los cubren los compuestos con fecha_hora (ver Meta.indexes).
    propuesta = models.ForeignKey(
        'propuestas.Propuesta',
        on_delete=models.PROTECT,
        db_column='id_propuesta',
        db_index=False,
        blank=True,
        null=True,
        related_name='historial',
    )
    informe = models.ForeignKey(
        'informes.Informe',
        on_delete=models.PROTECT,
        db_column='id_informe',
        db_index=False,
        blank=True,
        null=True,
        related_name='historial',
    )
    # Usuario que realmente ejecutó la acción.
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario',
        related_name='historial_estados',
    )
    tipo_rechazo = models.ForeignKey(
        'parametrizacion.TipoRechazo',
        on_delete=models.PROTECT,
        db_column='id_tipo_rechazo',
        blank=True,
        null=True,
        related_name='historial',
    )
    estado_anterior = models.CharField(
        max_length=30, choices=EstadoTramite, blank=True, null=True
    )
    estado_nuevo = models.CharField(max_length=30, choices=EstadoTramite)
    observacion = models.TextField(blank=True)
    motivo_reactivacion = models.TextField(blank=True)
    # Vocabulario todavía sin definir: texto libre.
    tipo_accion = models.CharField(max_length=30)
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'historial_estado'
        verbose_name = 'historial de estado'
        verbose_name_plural = 'historial de estados'
        constraints = [
            models.CheckConstraint(
                condition=Q(propuesta__isnull=False, informe__isnull=True)
                | Q(propuesta__isnull=True, informe__isnull=False),
                name='historial_estado_propuesta_o_informe',
            ),
            models.CheckConstraint(
                condition=Q(estado_anterior__isnull=True)
                | Q(estado_anterior__in=EstadoTramite.values),
                name='historial_estado_anterior_valido',
            ),
            models.CheckConstraint(
                condition=Q(estado_nuevo__in=EstadoTramite.values),
                name='historial_estado_nuevo_valido',
            ),
        ]
        indexes = [
            models.Index(fields=['propuesta', 'fecha_hora'], name='historial_propuesta_fecha_idx'),
            models.Index(fields=['informe', 'fecha_hora'], name='historial_informe_fecha_idx'),
        ]

    def __str__(self):
        return f'{self.estado_anterior} → {self.estado_nuevo} ({self.fecha_hora:%Y-%m-%d %H:%M})'


class Notificacion(models.Model):
    """Aviso dentro de SISTRA. Puede ser general o de una propuesta o un
    informe, pero no de ambos. `fecha_lectura` NULL significa no leída."""

    id_notificacion = models.BigAutoField(primary_key=True)
    # El índice lo cubre notificacion_usuario_lectura_idx (usuario, fecha_lectura).
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario',
        db_index=False,
        related_name='notificaciones',
    )
    propuesta = models.ForeignKey(
        'propuestas.Propuesta',
        on_delete=models.PROTECT,
        db_column='id_propuesta',
        blank=True,
        null=True,
        related_name='notificaciones',
    )
    informe = models.ForeignKey(
        'informes.Informe',
        on_delete=models.PROTECT,
        db_column='id_informe',
        blank=True,
        null=True,
        related_name='notificaciones',
    )
    tipo = models.CharField(max_length=50)
    mensaje = models.TextField()
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    fecha_lectura = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'notificacion'
        verbose_name = 'notificación'
        verbose_name_plural = 'notificaciones'
        constraints = [
            models.CheckConstraint(
                condition=Q(propuesta__isnull=True) | Q(informe__isnull=True),
                name='notificacion_no_propuesta_e_informe',
            ),
        ]
        indexes = [
            models.Index(fields=['usuario', 'fecha_lectura'], name='notificacion_usuario_lect_idx'),
        ]

    def __str__(self):
        return f'{self.tipo} · {self.usuario}'


class Auditoria(models.Model):
    """Acciones relevantes, éxitos y fallos. Nunca guarda contraseñas ni secretos.

    `id_registro_afectado` es una referencia lógica sin FK, porque puede
    apuntar a cualquier tabla.
    """

    id_auditoria = models.BigAutoField(primary_key=True)
    # NULL si no se identifica al usuario (por ejemplo, un ingreso fallido).
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column='id_usuario',
        blank=True,
        null=True,
        related_name='auditorias',
    )
    accion = models.CharField(max_length=100)
    tabla_afectada = models.CharField(max_length=80)
    id_registro_afectado = models.BigIntegerField(blank=True, null=True)
    detalle = models.TextField(blank=True)
    resultado = models.CharField(max_length=30)
    fecha_hora = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'auditoria'
        verbose_name = 'registro de auditoría'
        verbose_name_plural = 'auditoría'
        indexes = [
            models.Index(fields=['fecha_hora'], name='auditoria_fecha_hora_idx'),
        ]

    def __str__(self):
        return f'{self.accion} · {self.resultado} ({self.fecha_hora:%Y-%m-%d %H:%M})'
