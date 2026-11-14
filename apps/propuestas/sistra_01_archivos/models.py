"""
models.py — Módulo "Registro y Gestión de Propuesta de Trabajo Social" (SIS-20 / BR-01, §5.2)
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .signals import propuesta_enviada


class EstadoPropuesta(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    EN_REVISION = "EN_REVISION", "En revisión"
    REQUIERE_MODIFICACION = "REQUIERE_MODIFICACION", "Requiere modificación"
    APROBADO = "APROBADO", "Aprobado"


# Estados que cuentan como "propuesta activa" (regla 5).
# Si más adelante se agrega un estado terminal (p. ej. RECHAZADO o CANCELADO),
# NO lo incluyas aquí: así el estudiante podrá crear una nueva propuesta.
ESTADOS_ACTIVOS = [
    EstadoPropuesta.BORRADOR,
    EstadoPropuesta.EN_REVISION,
    EstadoPropuesta.REQUIERE_MODIFICACION,
    EstadoPropuesta.APROBADO,
]

# Estados en los que el formulario admite edición (reglas 2 y 4).
ESTADOS_EDITABLES = (EstadoPropuesta.BORRADOR, EstadoPropuesta.REQUIERE_MODIFICACION)

# Campos que deben estar diligenciados para poder enviar y que alimentan la barra de progreso.
CAMPOS_OBLIGATORIOS = (
    "titulo",
    "entidad",
    "sector",
    "poblacion_beneficiada",
    "impacto_social",
    "descripcion_problema",
    "justificacion",
    "objetivo_general",
    "objetivos_especificos",
    "metodologia",
)


class Sector(models.TextChoices):
    EDUCACION = "EDUCACION", "Educación"
    SALUD = "SALUD", "Salud"
    AMBIENTAL = "AMBIENTAL", "Ambiental"
    COMUNITARIO = "COMUNITARIO", "Desarrollo comunitario"
    AGROPECUARIO = "AGROPECUARIO", "Agropecuario"
    TECNOLOGIA = "TECNOLOGIA", "Tecnología"
    OTRO = "OTRO", "Otro"


class Notificacion(models.Model):
    """Notificación interna de la plataforma."""

    destinatario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificaciones"
    )
    mensaje = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creada"]

    def __str__(self):
        return f"{self.destinatario} · {self.mensaje[:40]}"


class PropuestaTrabajoSocial(models.Model):
    estudiante = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="propuestas_trabajo_social"
    )
    director = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="propuestas_dirigidas",
    )

    # Todos los campos admiten blank=True: un borrador puede guardarse incompleto.
    # La obligatoriedad real se valida al enviar (ver forms.py / enviar()).
    titulo = models.CharField("Título de la propuesta", max_length=255, blank=True)
    entidad = models.CharField("Entidad", max_length=255, blank=True)
    sector = models.CharField("Sector", max_length=20, choices=Sector.choices, blank=True)
    poblacion_beneficiada = models.TextField("Población beneficiada", blank=True)
    impacto_social = models.TextField("Impacto social", blank=True)
    descripcion_problema = models.TextField("Descripción del problema", blank=True)
    justificacion = models.TextField("Justificación", blank=True)
    objetivo_general = models.TextField("Objetivo general", blank=True)
    objetivos_especificos = models.TextField("Objetivos específicos", blank=True)
    metodologia = models.TextField("Metodología", blank=True)

    estado = models.CharField(
        max_length=25, choices=EstadoPropuesta.choices, default=EstadoPropuesta.BORRADOR, db_index=True
    )
    observaciones_director = models.TextField(blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    fecha_envio = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Propuesta de Trabajo Social"
        verbose_name_plural = "Propuestas de Trabajo Social"
        constraints = [
            # Garantía a nivel de BD (regla 5): índice único parcial.
            # SQL equivalente (PostgreSQL / SQLite):
            #   CREATE UNIQUE INDEX uniq_propuesta_activa_por_estudiante
            #   ON propuestas_propuestatrabajosocial (estudiante_id)
            #   WHERE estado IN ('BORRADOR','EN_REVISION','REQUIERE_MODIFICACION','APROBADO');
            # MySQL/MariaDB no soportan índices parciales: ahí rige solo la validación en clean().
            models.UniqueConstraint(
                fields=["estudiante"],
                condition=Q(estado__in=[e.value for e in ESTADOS_ACTIVOS]),
                name="uniq_propuesta_activa_por_estudiante",
            )
        ]

    def __str__(self):
        return f"{self.titulo or 'Sin título'} — {self.estudiante} ({self.get_estado_display()})"

    # ------------------------------------------------------------------ validación
    def clean(self):
        """Regla 5: un estudiante no puede tener dos propuestas activas."""
        super().clean()
        if self.estudiante_id and self.estado in [e.value for e in ESTADOS_ACTIVOS]:
            otras = PropuestaTrabajoSocial.objects.filter(
                estudiante_id=self.estudiante_id, estado__in=ESTADOS_ACTIVOS
            ).exclude(pk=self.pk)
            if otras.exists():
                raise ValidationError(
                    "Ya tienes una propuesta activa; no puedes crear otra mientras siga vigente."
                )

    # ------------------------------------------------------------------ consultas de estado
    @property
    def es_editable(self) -> bool:
        return self.estado in ESTADOS_EDITABLES

    def campos_faltantes(self) -> list[str]:
        return [
            self._meta.get_field(n).verbose_name
            for n in CAMPOS_OBLIGATORIOS
            if not str(getattr(self, n) or "").strip()
        ]

    @property
    def porcentaje_avance(self) -> int:
        llenos = sum(1 for n in CAMPOS_OBLIGATORIOS if str(getattr(self, n) or "").strip())
        return round(100 * llenos / len(CAMPOS_OBLIGATORIOS))

    # ------------------------------------------------------------------ transiciones (regla 4)
    def enviar(self):
        """BORRADOR | REQUIERE_MODIFICACION -> EN_REVISION, bloquea edición y notifica al Director."""
        if not self.es_editable:
            raise ValidationError("La propuesta no se puede enviar en su estado actual.")
        if self.campos_faltantes():
            raise ValidationError("Faltan campos obligatorios: " + ", ".join(self.campos_faltantes()))
        if not self.director_id:
            raise ValidationError("No tienes un Director asignado para recibir la propuesta.")

        es_reenvio = self.estado == EstadoPropuesta.REQUIERE_MODIFICACION
        from django.utils import timezone

        self.estado = EstadoPropuesta.EN_REVISION
        self.fecha_envio = timezone.now()
        self.save(update_fields=["estado", "fecha_envio", "actualizada"])
        propuesta_enviada.send(sender=type(self), propuesta=self, es_reenvio=es_reenvio)

    def solicitar_modificacion(self, observaciones: str = ""):
        """Acción del Director: EN_REVISION -> REQUIERE_MODIFICACION (desbloquea el formulario)."""
        if self.estado != EstadoPropuesta.EN_REVISION:
            raise ValidationError("Solo una propuesta en revisión puede devolverse.")
        self.estado = EstadoPropuesta.REQUIERE_MODIFICACION
        self.observaciones_director = observaciones
        self.save(update_fields=["estado", "observaciones_director", "actualizada"])

    def aprobar(self):
        if self.estado != EstadoPropuesta.EN_REVISION:
            raise ValidationError("Solo una propuesta en revisión puede aprobarse.")
        self.estado = EstadoPropuesta.APROBADO
        self.save(update_fields=["estado", "actualizada"])
