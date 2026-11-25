from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.dashboard.services import evaluar_semaforo
from apps.informes.models import Informe
from apps.personas.models import DirectorCarrera
from apps.propuestas.forms.aprobacion import (
    RESULTADO_EXITO,
    RESULTADO_FALLO,
    obtener_limites_semaforo,
)
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.usuarios.models import Estado

MSG_14_03 = 'Tienes {cantidad} registros en {nivel} esperando tu revisión.'

TIPOS_ALERTA_SEMAFORO = {
    'amarillo': 'SEMAFORO_AMARILLO',
    'rojo': 'SEMAFORO_ROJO',
}


def _fecha_inicio_revision(registro, es_propuesta):
    """Obtiene la fecha desde la cual el trámite entró al ciclo actual de revisión."""
    if registro.fecha_envio:
        return registro.fecha_envio

    filtro_tramite = {'propuesta': registro} if es_propuesta else {'informe': registro}
    ultimo_ingreso = (
        HistorialEstado.objects.filter(
            estado_nuevo=EstadoTramite.EN_REVISION,
            **filtro_tramite,
        )
        .order_by('-fecha_hora')
        .first()
    )
    if ultimo_ingreso:
        return ultimo_ingreso.fecha_hora

    return registro.fecha_actualizacion or registro.fecha_creacion


def _ya_notificado_en_ciclo(director_usuario, tipo_alerta, registro, es_propuesta):
    """Comprueba si ya existe un aviso de ese color en el ciclo actual de revisión."""
    filtro_enlace = {'propuesta': registro} if es_propuesta else {'informe': registro}
    ultima_notif = (
        Notificacion.objects.filter(
            usuario=director_usuario,
            tipo=tipo_alerta,
            **filtro_enlace,
        )
        .order_by('-fecha_creacion')
        .first()
    )
    if not ultima_notif:
        return False

    fecha_inicio = _fecha_inicio_revision(registro, es_propuesta)
    if fecha_inicio and ultima_notif.fecha_creacion < fecha_inicio:
        return False

    salio_despues = HistorialEstado.objects.filter(
        estado_anterior=EstadoTramite.EN_REVISION,
        fecha_hora__gte=ultima_notif.fecha_creacion,
        **filtro_enlace,
    ).exists()
    return not salio_despues


def _directores_activos_por_carrera():
    """Devuelve un mapa `{id_carrera: usuario_director}` para directores activos."""
    asignaciones = DirectorCarrera.objects.filter(
        activo=True,
        director__usuario__estado=Estado.ACTIVO,
        director__usuario__rol__estado=Estado.ACTIVO,
    ).select_related('director__usuario')

    return {asig.carrera_id: asig.director.usuario for asig in asignaciones}


class Command(BaseCommand):
    help = (
        'Genera notificaciones internas para los Directores cuando propuestas o '
        'informes en revisión pasan a semáforo amarillo o rojo.'
    )

    def handle(self, *args, **options):
        ahora = timezone.now()
        self.stdout.write('Iniciando revisión de alertas de semáforo...')

        try:
            limites = obtener_limites_semaforo()
            directores_por_carrera = _directores_activos_por_carrera()

            propuestas = (
                Propuesta.objects.filter(
                    estado=EstadoTramite.EN_REVISION,
                    archivada=False,
                )
                .select_related('proceso__estudiante_carrera')
                .order_by('pk')
            )
            informes = (
                Informe.objects.filter(
                    estado=EstadoTramite.EN_REVISION,
                    archivado=False,
                )
                .select_related('propuesta__proceso__estudiante_carrera')
                .order_by('pk')
            )

            candidatos = []
            conteo_por_director_y_nivel = Counter()

            for propuesta in propuestas:
                carrera_id = propuesta.proceso.estudiante_carrera.carrera_id
                director_usuario = directores_por_carrera.get(carrera_id)
                if not director_usuario:
                    continue

                semaforo = evaluar_semaforo(propuesta=propuesta, limites=limites)
                nivel = semaforo['nivel']
                if nivel not in TIPOS_ALERTA_SEMAFORO:
                    continue

                conteo_por_director_y_nivel[(director_usuario.pk, nivel)] += 1
                candidatos.append(
                    {
                        'es_propuesta': True,
                        'registro': propuesta,
                        'director': director_usuario,
                        'nivel': nivel,
                    }
                )

            for informe in informes:
                carrera_id = informe.propuesta.proceso.estudiante_carrera.carrera_id
                director_usuario = directores_por_carrera.get(carrera_id)
                if not director_usuario:
                    continue

                semaforo = evaluar_semaforo(informe=informe, limites=limites)
                nivel = semaforo['nivel']
                if nivel not in TIPOS_ALERTA_SEMAFORO:
                    continue

                conteo_por_director_y_nivel[(director_usuario.pk, nivel)] += 1
                candidatos.append(
                    {
                        'es_propuesta': False,
                        'registro': informe,
                        'director': director_usuario,
                        'nivel': nivel,
                    }
                )

            creadas = 0
            for item in candidatos:
                es_propuesta = item['es_propuesta']
                registro = item['registro']
                director_usuario = item['director']
                nivel = item['nivel']
                tipo_alerta = TIPOS_ALERTA_SEMAFORO[nivel]

                if _ya_notificado_en_ciclo(
                    director_usuario,
                    tipo_alerta,
                    registro,
                    es_propuesta,
                ):
                    continue

                filtro_enlace = (
                    {'propuesta': registro} if es_propuesta else {'informe': registro}
                )
                cantidad_en_nivel = conteo_por_director_y_nivel[
                    (director_usuario.pk, nivel)
                ]
                mensaje = MSG_14_03.format(
                    cantidad=cantidad_en_nivel,
                    nivel=nivel,
                )

                with transaction.atomic():
                    notif = Notificacion.objects.create(
                        usuario=director_usuario,
                        tipo=tipo_alerta,
                        mensaje=mensaje,
                        fecha_creacion=ahora,
                        **filtro_enlace,
                    )
                    tipo_tramite = 'Propuesta' if es_propuesta else 'Informe'
                    Auditoria.objects.create(
                        usuario=None,
                        accion=f'Alerta de semáforo {nivel}',
                        tabla_afectada='notificacion',
                        id_registro_afectado=notif.pk,
                        detalle=(
                            f'Alerta {nivel} generada para director '
                            f'{director_usuario.correo_institucional} '
                            f'({tipo_tramite}: {registro.codigo}).'
                        ),
                        resultado=RESULTADO_EXITO,
                        fecha_hora=ahora,
                    )

                creadas += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f'Finalizado: {creadas} alertas de semáforo generadas.'
                )
            )
        except Exception as exc:
            Auditoria.objects.create(
                usuario=None,
                accion='Alerta de semáforo',
                tabla_afectada='notificacion',
                id_registro_afectado=None,
                detalle=f'Error ejecutando alerta_semaforo: {exc}',
                resultado=RESULTADO_FALLO,
                fecha_hora=ahora,
            )
            raise
