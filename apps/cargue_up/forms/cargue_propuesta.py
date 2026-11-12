"""SISTRA-03 · Cargue al sistema de UP: formularios y lógica de validación.

Cumple con el requerimiento de negocio BR-03 (SISTRA-03).
Valida las reglas de negocio:
- RN-01: Acciones habilitadas solo cuando el estado del proyecto es Aprobado.
- RN-04: Solo el estudiante dueño puede notificar; se registra una sola vez por proyecto.
- RN-05: Naturaleza declarativa del cargue.
- RN-07: Suspensión de recordatorios al cambiar estado.
- CA-09: Protección contra envíos duplicados / doble clic.
- CA-11: Fecha de cargue no puede ser posterior a la fecha actual.
"""

from datetime import date
from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.personas.models import DirectorCarrera
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion


LONGITUD_MAXIMA_OBSERVACIONES = 500

# Mensajes oficiales de la Matriz de Mensajes (BR-03)
MSG_XX_01 = (
    "Tu proyecto aún no ha sido aprobado por tu docente. Podrás cargarlo en el sistema "
    "de la UP cuando su estado sea Aprobado."
)
MSG_XX_02 = (
    "Tu docente no aprobó tu proyecto, por lo que aún no puedes cargarlo en la UP. "
    "Consulta la respuesta de tu docente."
)
MSG_XX_03 = (
    "Tu proyecto fue aprobado. Descárgalo y cárgalo en el sistema de la UP. Mientras no "
    "notifiques el cargue, te enviaremos un recordatorio semanal por correo."
)
MSG_XX_04 = (
    "Se abrió el sistema de la UP en una pestaña nueva. Cuando termines el cargue, "
    "regresa a Sistra UP y notifica a tu docente."
)
MSG_XX_05 = (
    "¿Confirmas que ya cargaste tu proyecto en el sistema de la UP? Se notificará a tu "
    "docente y dejarás de recibir recordatorios."
)
MSG_XX_06 = (
    "Listo, notificamos a tu docente que cargaste tu proyecto en el sistema de la UP. "
    "Quedas a la espera de una nueva actualización del estado."
)
MSG_XX_07 = "Ya notificaste el cargue el {fecha}. Tu proyecto está a la espera de una nueva actualización de estado."
MSG_XX_08 = (
    "Aún no has enviado tu proyecto de horas sociales. Envíalo para revisión de tu docente; "
    "cuando sea aprobado podrás cargarlo en la UP desde aquí."
)
MSG_XX_09 = "La fecha de cargue no puede ser posterior a hoy."
MSG_XX_10 = "Indica la fecha en que cargaste el proyecto en la UP."
MSG_XX_11 = "Las observaciones no pueden superar los 500 caracteres."
MSG_XX_12 = "No pudimos descargar tu proyecto. Inténtalo de nuevo; si el problema continúa, contacta a tu docente."
MSG_XX_13 = "No pudimos registrar tu notificación. Inténtalo de nuevo en unos minutos."
MSG_XX_14 = "El estado de tu proyecto cambió y esta acción ya no está disponible. Actualizamos la pantalla."
MSG_XX_15 = "El enlace al sistema de la UP no está disponible por ahora. Contacta a tu docente."
MSG_XX_16 = "Tu sesión expiró. Inicia sesión nuevamente para continuar."
MSG_XX_17 = "No tienes permiso para realizar esta acción."


def sanitizar_texto(valor: str) -> str:
    """Elimina espacios redundantes y sanitiza texto."""
    return valor.strip() if valor else ""


def registrar_auditoria(
    usuario,
    accion: str,
    tabla_afectada: str = "cargue_up",
    id_registro: int | None = None,
    detalle: str = "",
    resultado: str = "EXITO",
) -> None:
    """Registra eventos de auditoría obligatorios para BR-03 (CA-12)."""
    try:
        Auditoria.objects.create(
            usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
            accion=accion[:100],
            tabla_afectada=tabla_afectada[:80],
            id_registro_afectado=id_registro,
            detalle=detalle,
            resultado=resultado[:30],
            fecha_hora=timezone.now(),
        )
    except Exception:
        # La auditoría no debe romper la experiencia si ocurre una excepción no crítica
        pass


class NotificarCargueForm(forms.Form):
    """Formulario del modal para que el estudiante confirme el cargue en UP."""

    fecha_cargue = forms.DateField(
        required=True,
        error_messages={
            "required": MSG_XX_10,
            "invalid": "Ingresa una fecha válida.",
        },
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control",
                "id": "cup_fecha_cargue",
            }
        ),
    )
    observaciones = forms.CharField(
        required=False,
        max_length=LONGITUD_MAXIMA_OBSERVACIONES,
        error_messages={
            "max_length": MSG_XX_11,
        },
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Observaciones opcionales (máx. 500 caracteres)...",
                "maxlength": str(LONGITUD_MAXIMA_OBSERVACIONES),
                "id": "cup_observaciones",
            }
        ),
    )

    def __init__(self, *args, propuesta: Propuesta | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.propuesta = propuesta

    def clean_fecha_cargue(self) -> date:
        fecha = self.cleaned_data.get("fecha_cargue")
        if not fecha:
            raise ValidationError(MSG_XX_10)

        hoy = timezone.localdate()
        if fecha > hoy:
            raise ValidationError(MSG_XX_09)

        # Validación opcional recomendada: no anterior a la fecha de aprobación
        if self.propuesta and self.propuesta.fecha_envio:
            fecha_minima = self.propuesta.fecha_envio.date()
            if fecha < fecha_minima:
                raise ValidationError(
                    f"La fecha de cargue no puede ser anterior a la fecha de radicación del proyecto ({fecha_minima.strftime('%d/%m/%Y')})."
                )

        return fecha

    def clean_observaciones(self) -> str:
        obs = self.cleaned_data.get("observaciones", "")
        obs_limpia = sanitizar_texto(obs)
        if len(obs_limpia) > LONGITUD_MAXIMA_OBSERVACIONES:
            raise ValidationError(MSG_XX_11)
        return obs_limpia

    def procesar(self, propuesta: Propuesta, estudiante_usuario) -> CargueUp:
        """Aplica la transición de cargue dentro de una transacción atómica protegida contra concurrencia.
        
        - Bloquea la fila con select_for_update.
        - Valida que siga en estado 'Aprobado' (RN-01, E4).
        - Valida que no exista ya un registro de cargue previo (E7, CA-09).
        - Crea el registro CargueUp.
        - Transiciona la propuesta a 'Subido en UP' (EstadoTramite.SUBIDO_EN_UP).
        - Registra HistorialEstado, Auditoria y Notificación en sistema al docente.
        """
        fecha_cargue = self.cleaned_data["fecha_cargue"]
        observaciones = self.cleaned_data["observaciones"]

        with transaction.atomic():
            # Bloqueo estricto a nivel de fila para evitar envíos duplicados concurrentes
            propuesta_lock = (
                Propuesta.objects.select_for_update()
                .select_related("proceso__estudiante_carrera__carrera")
                .get(pk=propuesta.pk)
            )

            # E4: El estado cambió mientras el estudiante tenía la pantalla abierta
            if propuesta_lock.estado != EstadoTramite.APROBADO:
                registrar_auditoria(
                    usuario=estudiante_usuario,
                    accion="NOTIFICAR_CARGUE_RECHAZADO_ESTADO_INVALIDO",
                    tabla_afectada="propuesta",
                    id_registro=propuesta_lock.pk,
                    detalle=f"Estado actual: {propuesta_lock.estado}. Se esperaba: {EstadoTramite.APROBADO}",
                    resultado="RECHAZADO",
                )
                raise ValidationError(MSG_XX_14)

            # E7 / CA-09: Doble clic o envío duplicado: solo una notificación activa por proyecto
            ya_cargado = CargueUp.objects.filter(propuesta=propuesta_lock).exists()
            if ya_cargado:
                registrar_auditoria(
                    usuario=estudiante_usuario,
                    accion="NOTIFICAR_CARGUE_DUPLICADO",
                    tabla_afectada="cargue_up",
                    id_registro=propuesta_lock.pk,
                    detalle="Intento de notificación duplicada bloqueado.",
                    resultado="BLOQUEADO",
                )
                raise ValidationError("Ya se encuentra registrada una notificación de cargue para este proyecto.")

            # 1. Crear el registro en cargue_up
            cargue = CargueUp.objects.create(
                propuesta=propuesta_lock,
                fecha_declaracion=timezone.now(),
                estado_verificacion=EstadoVerificacion.PENDIENTE,
                observacion=observaciones,
            )

            # 2. Actualizar estado de la propuesta a Subido en UP
            estado_anterior = propuesta_lock.estado
            propuesta_lock.estado = EstadoTramite.SUBIDO_EN_UP
            propuesta_lock.save(update_fields=["estado", "fecha_actualizacion"])

            # 3. Registrar en historial_estado (trazabilidad de cambios de estado)
            HistorialEstado.objects.create(
                propuesta=propuesta_lock,
                usuario=estudiante_usuario,
                estado_anterior=estado_anterior,
                estado_nuevo=EstadoTramite.SUBIDO_EN_UP,
                observacion=observaciones,
                tipo_accion="Cargue en UP",
                fecha_hora=timezone.now(),
            )

            # 4. Notificar internamente al docente/director asignado
            try:
                carrera = propuesta_lock.proceso.estudiante_carrera.carrera
                asignacion = (
                    DirectorCarrera.objects.filter(carrera=carrera, activo=True)
                    .select_related("director__usuario")
                    .first()
                )
                if asignacion and asignacion.director and asignacion.director.usuario:
                    nombre_estudiante = getattr(estudiante_usuario, "nombre", str(estudiante_usuario))
                    nombre_proyecto = propuesta_lock.titulo or propuesta_lock.codigo
                    Notificacion.objects.create(
                        usuario=asignacion.director.usuario,
                        propuesta=propuesta_lock,
                        tipo="Cargue en UP",
                        mensaje=(
                            f"{nombre_estudiante} notificó que cargó su proyecto «{nombre_proyecto}» "
                            f"en el sistema de la UP el {fecha_cargue.strftime('%d/%m/%Y')}."
                        ),
                        fecha_creacion=timezone.now(),
                    )
            except Exception:
                # E5: Si falla solo el aviso al docente, la notificación queda registrada
                pass

            # 5. Registro de auditoría exitoso
            registrar_auditoria(
                usuario=estudiante_usuario,
                accion="NOTIFICAR_CARGUE_EXITOSO",
                tabla_afectada="cargue_up",
                id_registro=cargue.pk,
                detalle=(
                    f"Propuesta: {propuesta_lock.codigo} | Fecha declarada: {fecha_cargue.strftime('%Y-%m-%d')} | "
                    f"Observaciones: {observaciones or 'Sin observaciones'}"
                ),
                resultado="EXITO",
            )

            return cargue
