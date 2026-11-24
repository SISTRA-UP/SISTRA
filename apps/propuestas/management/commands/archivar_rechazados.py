"""SIS-52 / SISTRA-07 · B6a/B6b: archiva propuestas e informes rechazados (RG-13).

Cada trámite Rechazado y no archivado se archiva cuando su último rechazo
(historial) supera su plazo propio de Parametrización. Archivar no borra
ni cambia el estado: el trámite deja de contar como activo y ya no se reactiva.

Uso (programarlo una vez al día): uv run python manage.py archivar_rechazados
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.informes.models import Informe
from apps.parametrizacion import servicios
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, _auditar
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado

PLAZO_PROPUESTAS = 'dias_archivado_propuesta_rechazada'
PLAZO_INFORMES = 'dias_archivado_informe_rechazado'


class Command(BaseCommand):
    help = 'Archiva propuestas e informes rechazados que superan su plazo en Parametrización.'

    def handle(self, *args, **options):
        plazo = servicios.obtener_entero(PLAZO_PROPUESTAS)
        if plazo is None:
            self.stdout.write(f'No hay plazo configurado ({PLAZO_PROPUESTAS}): no se archivó ninguna propuesta.')
        else:
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
                # Conserva la corrección de B6a: archivado y auditoría son atómicos.
                with transaction.atomic():
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

        plazo_informes = servicios.obtener_entero(PLAZO_INFORMES)
        if plazo_informes is None:
            self.stdout.write(
                f'No hay plazo configurado ({PLAZO_INFORMES}): no se archivó ningún informe.'
            )
            return

        ahora = timezone.now()
        limite = ahora - timedelta(days=plazo_informes)
        informes_vencidos = (
            Informe.objects.filter(estado=EstadoTramite.RECHAZADO, archivado=False)
            .annotate(
                ultimo_rechazo=Max(
                    'historial__fecha_hora',
                    filter=Q(historial__estado_nuevo=EstadoTramite.RECHAZADO),
                )
            )
            .filter(ultimo_rechazo__lt=limite)
            .values_list('pk', flat=True)
        )

        archivados = 0
        for id_informe in informes_vencidos.iterator():
            with transaction.atomic():
                informe = Informe.objects.select_for_update().get(pk=id_informe)
                # Comprueba otra vez el estado y el último rechazo bajo bloqueo:
                # el Director podría haber reactivado o rechazado de nuevo el informe.
                ultimo_rechazo = (
                    HistorialEstado.objects.filter(
                        informe_id=id_informe, estado_nuevo=EstadoTramite.RECHAZADO,
                    )
                    .order_by('-fecha_hora')
                    .values_list('fecha_hora', flat=True)
                    .first()
                )
                if (
                    informe.archivado
                    or informe.estado != EstadoTramite.RECHAZADO
                    or ultimo_rechazo is None
                    or ultimo_rechazo >= limite
                ):
                    continue

                informe.archivado = True
                informe.fecha_archivado = ahora
                informe.save(update_fields=['archivado', 'fecha_archivado'])
                Auditoria.objects.create(
                    usuario=None,
                    accion='ARCHIVAR_INFORME_RECHAZADO',
                    tabla_afectada='informe',
                    id_registro_afectado=informe.pk,
                    detalle=(
                        f'Informe {informe.codigo} archivado automáticamente: '
                        f'último rechazo hace más de {plazo_informes} días (RG-13).'
                    ),
                    resultado=RESULTADO_EXITO,
                    fecha_hora=ahora,
                )
                archivados += 1

        self.stdout.write(f'Informes archivados: {archivados} (plazo: {plazo_informes} días).')
