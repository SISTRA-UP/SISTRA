"""SIS-52 · B6a: archiva las propuestas rechazadas que nadie reactivó (RG-13).

Una propuesta Rechazada y no archivada se archiva cuando su último rechazo (historial)
tiene más días que el plazo `dias_archivado_propuesta_rechazada` de Parametrización.
Archivar no borra: la propuesta deja de contar como activa y ya no se puede reactivar.
Si se reactivó antes del plazo ya no está en Rechazado y no se toca.

Uso (programarlo una vez al día): uv run python manage.py archivar_rechazados
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.parametrizacion import servicios
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, _auditar
from apps.propuestas.models import EstadoTramite, Propuesta

PLAZO_PROPUESTAS = 'dias_archivado_propuesta_rechazada'


class Command(BaseCommand):
    help = 'Archiva las propuestas rechazadas que superan el plazo definido en Parametrización.'

    def handle(self, *args, **options):
        plazo = servicios.obtener_entero(PLAZO_PROPUESTAS)
        if plazo is None:
            self.stdout.write(f'No hay plazo configurado ({PLAZO_PROPUESTAS}): no se archivó ninguna propuesta.')
            return

        ahora = timezone.now()
        vencidas = (
            Propuesta.objects.filter(estado=EstadoTramite.RECHAZADO, archivada=False)
            .annotate(
                ultimo_rechazo=Max(
                    'historial__fecha_hora',
                    filter=Q(historial__estado_nuevo=EstadoTramite.RECHAZADO),
                )
            )
            .filter(ultimo_rechazo__lt=ahora - timedelta(days=plazo))
            .select_related('proceso__estudiante_carrera__estudiante__usuario')
        )

        archivadas = 0
        for propuesta in vencidas:
            # Archivado y auditoría en la misma transacción: si la auditoría falla, no se archiva.
            with transaction.atomic():
                # Se vuelve a exigir Rechazado y no archivada en el mismo UPDATE: si el Director la
                # reactivó entre la consulta y este punto, no se archiva.
                if not Propuesta.objects.filter(
                    pk=propuesta.pk, estado=EstadoTramite.RECHAZADO, archivada=False
                ).update(archivada=True, fecha_archivado=ahora):
                    continue
                _auditar(
                    None,
                    'ARCHIVAR_PROPUESTA_RECHAZADA',
                    propuesta,
                    detalle_extra=f'Archivada automáticamente: rechazada hace más de {plazo} días (RG-13).',
                    resultado=RESULTADO_EXITO,
                )
            archivadas += 1

        self.stdout.write(f'Propuestas archivadas: {archivadas} (plazo: {plazo} días).')
