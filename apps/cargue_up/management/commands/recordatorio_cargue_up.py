"""Comando de gestión para enviar recordatorios periódicos de cargue en la Plataforma UP.

Criterios 4 y 5 del requerimiento SISTRA-03 (BR-03):
- Revisa propuestas en estado 'Aprobado' que aún no tengan notificación de cargue en UP
  (o cuyo último cargue haya sido Rechazado en UP, volviendo a Aprobado).
- Crea avisos dentro de la plataforma (tabla Notificacion), sin envío de correos.
- Frecuencia configurable mediante Parametro 'recordatorio.frecuencia_dias' (por defecto 7 días).
- Deja de avisar tan pronto la propuesta no esté en Aprobado o pase a 'Subido en UP'.
"""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.parametrizacion.models import Parametro
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion


TIPO_NOTIFICACION = "RECORDATORIO_CARGUE_UP"
FRECUENCIA_DIAS_DEFAULT = 7


class Command(BaseCommand):
    help = "Envía recordatorios periódicos a estudiantes con propuestas aprobadas pendientes de cargue en UP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            help="Sobrescribe la frecuencia en días para la revisión (por defecto lee de Parametro o usa 7 días).",
        )

    def handle(self, *args, **options):
        ahora = timezone.now()

        # 1. Determinar frecuencia en días
        dias_cli = options.get("dias")
        if dias_cli is not None and dias_cli >= 0:
            frecuencia_dias = dias_cli
        else:
            param = Parametro.objects.filter(clave="recordatorio.frecuencia_dias").first()
            try:
                frecuencia_dias = int(param.valor) if param and param.valor else FRECUENCIA_DIAS_DEFAULT
            except (ValueError, TypeError):
                frecuencia_dias = FRECUENCIA_DIAS_DEFAULT

        self.stdout.write(f"Iniciando revisión de recordatorios (frecuencia: cada {frecuencia_dias} días)...")

        # 2. Consultar propuestas en Aprobado no archivadas
        propuestas_aprobadas = (
            Propuesta.objects.filter(
                estado=EstadoTramite.APROBADO,
                archivada=False,
            )
            .select_related(
                "proceso__estudiante_carrera__estudiante__usuario"
            )
        )

        enviados = 0

        for propuesta in propuestas_aprobadas:
            # Validar que no tenga un cargue en UP activo (Pendiente o Aprobado en UP)
            tiene_cargue_activo = CargueUp.objects.filter(
                propuesta=propuesta,
                estado_verificacion__in=[
                    EstadoVerificacion.PENDIENTE,
                    EstadoVerificacion.APROBADO_EN_UP,
                ],
            ).exists()

            if tiene_cargue_activo:
                continue

            # Obtener usuario estudiante
            try:
                usuario_estudiante = propuesta.proceso.estudiante_carrera.estudiante.usuario
            except Exception:
                continue

            # Revisar última notificación de recordatorio emitida para esta propuesta
            ultima_notif = (
                Notificacion.objects.filter(
                    propuesta=propuesta,
                    tipo=TIPO_NOTIFICACION,
                )
                .order_by("-fecha_creacion")
                .first()
            )

            if ultima_notif:
                # Si ya recibió recordatorio, verificar si ha transcurrido el intervalo
                if (ahora - ultima_notif.fecha_creacion) < timedelta(days=frecuencia_dias):
                    continue
            else:
                # Si no ha recibido recordatorio, calcular desde la fecha de aprobación
                historial_aprob = (
                    HistorialEstado.objects.filter(
                        propuesta=propuesta,
                        estado_nuevo=EstadoTramite.APROBADO,
                    )
                    .order_by("-fecha_hora")
                    .first()
                )
                fecha_base = historial_aprob.fecha_hora if historial_aprob else propuesta.fecha_actualizacion
                if (ahora - fecha_base) < timedelta(days=frecuencia_dias):
                    continue

            # Crear notificación dentro de la plataforma
            titulo_prop = propuesta.titulo or propuesta.codigo
            mensaje = (
                f"Recordatorio semanal: Tu propuesta «{titulo_prop}» fue aprobada. "
                "Recuerda radicarla en la Plataforma UP para continuar con tu proceso de horas sociales."
            )

            notif = Notificacion.objects.create(
                usuario=usuario_estudiante,
                propuesta=propuesta,
                tipo=TIPO_NOTIFICACION,
                mensaje=mensaje,
                fecha_creacion=ahora,
            )

            Auditoria.objects.create(
                usuario=None,
                accion="Envío de recordatorio cargue en UP",
                tabla_afectada="notificacion",
                id_registro_afectado=notif.pk,
                detalle=(
                    f"Recordatorio generado para estudiante {usuario_estudiante.correo_institucional} "
                    f"(Propuesta: {propuesta.codigo})."
                ),
                resultado="Éxito",
                fecha_hora=ahora,
            )

            enviados += 1

        self.stdout.write(
            self.style.SUCCESS(f"Finalizado: {enviados} recordatorios enviados exitosamente.")
        )

