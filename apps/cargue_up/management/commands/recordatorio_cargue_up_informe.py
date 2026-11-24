"""SISTRA-08 · Recordatorio semanal: informe Aprobado sin «Subido en UP».

- Revisa informes en estado 'Aprobado' no archivados que no tengan un cargue activo.
- Crea avisos dentro de la plataforma (Notificacion), sin correo.
- Frecuencia: Parametro 'recordatorio.frecuencia_dias' (por defecto 7), o --dias.
- Deja de avisar cuando el informe pasa a 'Subido en UP' (ya no está Aprobado).
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.cargue_up.views import aviso_informe_servicio as servicio
from apps.informes.models import Informe
from apps.parametrizacion.servicios import obtener_entero
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion

TIPO_NOTIFICACION = 'RECORDATORIO_CARGUE_UP_INFORME'
ACCION_AUDITORIA = 'Envío de recordatorio cargue en UP (informe)'
CLAVE_FRECUENCIA = 'recordatorio.frecuencia_dias'
FRECUENCIA_DIAS_DEFAULT = 7
MSG_08_03 = (
    'Tu informe está aprobado y aún no has indicado que lo subiste '
    'a la Plataforma UP.'
)


class Command(BaseCommand):
    help = 'Crea el recordatorio dentro de la plataforma para informes Aprobados pendientes de cargue en UP.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias', type=int,
            help='Sobrescribe la frecuencia en días (por defecto: parámetro o 7).',
        )

    def handle(self, *args, **options):
        ahora = timezone.now()
        dias = options.get('dias')
        if dias is None or dias < 0:
            dias = obtener_entero(CLAVE_FRECUENCIA, FRECUENCIA_DIAS_DEFAULT)
        frecuencia = timedelta(days=dias)
        self.stdout.write(f'Iniciando revisión de recordatorios del informe (cada {dias} días)...')

        pks = list(
            Informe.objects.filter(estado=servicio.APROBADO, archivado=False)
            .values_list('pk', flat=True)
        )
        enviados = 0
        for pk in pks:
            with transaction.atomic():
                informe = (
                    Informe.objects.select_for_update(of=('self',))
                    .select_related(servicio.RUTA_ESTUDIANTE)
                    .filter(pk=pk, estado=servicio.APROBADO, archivado=False)
                    .first()
                )
                if informe is None:          # cambió de estado mientras corría el comando
                    continue
                if CargueUp.objects.filter(
                    informe=informe,
                    estado_verificacion__in=[
                        EstadoVerificacion.PENDIENTE,
                        EstadoVerificacion.APROBADO_EN_UP,
                    ],
                ).exists():
                    continue

                ultima = (
                    Notificacion.objects.filter(informe=informe, tipo=TIPO_NOTIFICACION)
                    .order_by('-fecha_creacion').first()
                )
                if ultima:
                    fecha_base = ultima.fecha_creacion
                else:
                    aprobacion = (
                        HistorialEstado.objects
                        .filter(informe=informe, estado_nuevo=servicio.APROBADO)
                        .order_by('-fecha_hora').first()
                    )
                    fecha_base = aprobacion.fecha_hora if aprobacion else informe.fecha_actualizacion
                if (ahora - fecha_base) < frecuencia:
                    continue

                destinatario = informe.propuesta.proceso.estudiante_carrera.estudiante.usuario
                notif = Notificacion.objects.create(
                    usuario=destinatario, informe=informe, tipo=TIPO_NOTIFICACION,
                    mensaje=MSG_08_03, fecha_creacion=ahora,
                )
                Auditoria.objects.create(
                    usuario=None,
                    accion=ACCION_AUDITORIA,
                    tabla_afectada='notificacion',
                    id_registro_afectado=notif.pk,
                    detalle=(
                        f'Recordatorio generado para {destinatario.correo_institucional} '
                        f'(Informe: {informe.codigo}).'
                    ),
                    resultado=servicio.RESULTADO_EXITO,
                    fecha_hora=ahora,
                )
                enviados += 1

        self.stdout.write(self.style.SUCCESS(
            f'Finalizado: {enviados} recordatorios creados.'))