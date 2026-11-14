"""Vistas de montaje de informe (SISTRA-06).

Permite al estudiante registrar su informe de Trabajo Social,
guardarlo como borrador y enviarlo a revisión.

Preparado para integrarse con SISTRA-07 (Aprobación de informe).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.informes.forms.montaje import (
    InformeForm,
    MSG_06_01,
    MSG_06_02,
    MSG_06_03,
    MSG_06_04,
    MSG_06_05,
    MINIMO_CARACTERES,
)
from apps.informes.models import Informe
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
#  Importar las constantes desde el módulo de aprobacion (SISTRA-02)
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, RESULTADO_BLOQUEADO


ESTADOS_EDITABLES = [
    EstadoTramite.BORRADOR,
    EstadoTramite.REQUIERE_MODIFICACION,
]

ESTADOS_BLOQUEADOS = [
    EstadoTramite.EN_REVISION,
    EstadoTramite.APROBADO,
    EstadoTramite.SUBIDO_EN_UP,
    EstadoTramite.APROBADO_EN_UP,
]


def _calcular_avance(informe):
    """Calcula el % de avance. Un campo cuenta como lleno si tiene >= 50 caracteres."""
    campos = ['resultados', 'conclusiones', 'recomendaciones']
    llenos = 0
    for campo in campos:
        if isinstance(informe, dict):
            valor = informe.get(campo, '') or ''
        else:
            valor = getattr(informe, campo, '') or ''
        if len(valor.strip()) >= MINIMO_CARACTERES:
            llenos += 1
    return int((llenos / len(campos)) * 100)


def _registrar_auditoria(usuario, informe, accion, resultado, detalle):
    """Registra una acción en la tabla de auditoría."""
    Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tabla_afectada='informe',
        id_registro_afectado=informe.id_informe,  # ⬅️ Nombre correcto del campo
        detalle=detalle,
        resultado=resultado,
        fecha_hora=timezone.now(),
    )


@login_required
def inicio(request):
    """Vista principal de montaje de informe."""
    usuario = request.user

    # --- Validación: debe ser estudiante (403 si no lo es) ---
    from apps.personas.models import Estudiante
    try:
        estudiante = Estudiante.objects.get(usuario=usuario)
    except Estudiante.DoesNotExist:
        raise PermissionDenied(
            'Solo los estudiantes pueden montar informes.'
        )

    # --- Validación: debe tener propuesta APROBADO EN UP ---
    propuesta = Propuesta.objects.filter(
        proceso__estudiante_carrera__estudiante=estudiante,
        estado=EstadoTramite.APROBADO_EN_UP,
        archivada=False,
    ).first()

    if not propuesta:
        return render(request, 'informes/montaje/inicio.html', {
            'sin_acceso': True,
            'mensaje_error': MSG_06_05,
        })

    # --- Obtener informe activo (excluye los RECHAZADOS) ---
    informe = Informe.objects.filter(
        propuesta=propuesta,
        archivado=False,
    ).exclude(estado=EstadoTramite.RECHAZADO).first()

    # Si no hay informe activo, se crea uno nuevo con código único
    if not informe:
        n = Informe.objects.filter(propuesta=propuesta).count() + 1
        nuevo_codigo = f'INF-{propuesta.codigo.replace("PROP-", "")}-{n}'
        informe = Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=propuesta.periodo_academico,
            codigo=nuevo_codigo,
            estado=EstadoTramite.BORRADOR,
        )
        _registrar_auditoria(
            usuario,
            informe,
            'Crear informe',
            RESULTADO_EXITO,  #  Constante importada
            f'Código: {informe.codigo} | Versión: {informe.version_entrega}',
        )

    bloqueado = informe.estado in ESTADOS_BLOQUEADOS

    # --- Observación del Director (SISTRA-07) ---
    ultima_observacion = None
    if informe.estado == EstadoTramite.REQUIERE_MODIFICACION:
        ultima_observacion = HistorialEstado.objects.filter(
            informe=informe,
            estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
        ).order_by('-fecha_hora').first()

    # --- Manejo de POST ---
    if request.method == 'POST':
        #  CRÍTICO: Validar bloqueo en el servidor
        if informe.estado not in ESTADOS_EDITABLES:
            messages.error(request, MSG_06_04)
            _registrar_auditoria(
                usuario,
                informe,
                'Editar informe',
                RESULTADO_BLOQUEADO,  #  Constante importada
                f'Intento de edición en estado: {informe.estado}',
            )
            return redirect('informes:montaje')

        accion = request.POST.get('accion')
        estado_anterior = informe.estado
        form = InformeForm(request.POST, instance=informe, accion=accion)

        if form.is_valid():
            if accion == 'guardar_borrador':
                #  NO cambia el estado. Solo guarda los textos.
                informe = form.save()

                _registrar_auditoria(
                    usuario,
                    informe,
                    'Guardar borrador',
                    RESULTADO_EXITO,
                    f'Código: {informe.codigo} | Versión: {informe.version_entrega}',
                )

                messages.success(request, MSG_06_01)
                return redirect('informes:montaje')

            elif accion == 'enviar':
                avance_post = _calcular_avance(form.cleaned_data)

                if avance_post < 100:
                    messages.error(request, MSG_06_03)
                    return redirect('informes:montaje')

                informe = form.save(commit=False)
                informe.estado = EstadoTramite.EN_REVISION
                informe.fecha_envio = timezone.now()

                es_reenvio = (estado_anterior == EstadoTramite.REQUIERE_MODIFICACION)
                if es_reenvio:
                    informe.version_entrega += 1

                informe.save()

                # Historial
                HistorialEstado.objects.create(
                    informe=informe,
                    usuario=usuario,
                    estado_anterior=estado_anterior,
                    estado_nuevo=EstadoTramite.EN_REVISION,
                    tipo_accion='envio_informe',
                    fecha_hora=timezone.now(),
                )

                # Auditoría
                accion_auditoria = 'Reenviar informe' if es_reenvio else 'Enviar informe'
                _registrar_auditoria(
                    usuario,
                    informe,
                    accion_auditoria,
                    RESULTADO_EXITO,
                    f'Código: {informe.codigo} | Versión: {informe.version_entrega}',
                )

                # Notificación al Director
                from apps.personas.models import DirectorCarrera
                director_carrera = DirectorCarrera.objects.filter(
                    carrera=propuesta.proceso.estudiante_carrera.carrera,
                    activo=True,
                ).first()

                if director_carrera:
                    Notificacion.objects.create(
                        usuario=director_carrera.director.usuario,
                        informe=informe,
                        tipo='informe_enviado_revision',
                        mensaje=(
                            f'El estudiante {usuario.nombre} ha enviado '
                            f'su informe ({informe.codigo}) para revisión.'
                        ),
                        fecha_creacion=timezone.now(),
                    )

                messages.success(request, MSG_06_02)
                return redirect('informes:montaje')
    else:
        form = InformeForm(instance=informe)

    # --- Avance actualizado ---
    informe.refresh_from_db()
    avance = _calcular_avance(informe)

    # --- Clases Bootstrap ---
    if avance == 100:
        clase_progreso = 'bg-success'
    elif avance >= 50:
        clase_progreso = 'bg-warning text-dark'
    else:
        clase_progreso = 'bg-danger'

    clases_estado = {
        'Borrador': 'bg-secondary',
        'En revisión': 'bg-warning text-dark',
        'Requiere modificación': 'bg-info text-dark',
        'Aprobado': 'bg-success',
        'Rechazado': 'bg-danger',
        'Subido en UP': 'bg-primary',
        'Aprobado en UP': 'bg-primary',
    }
    clase_estado = clases_estado.get(informe.estado, 'bg-secondary')

    context = {
        'propuesta': propuesta,
        'informe': informe,
        'form': form,
        'avance': avance,
        'bloqueado': bloqueado,
        'ultima_observacion': ultima_observacion,
        'clase_progreso': clase_progreso,
        'clase_estado': clase_estado,
        'sin_acceso': False,
        'minimo_caracteres': MINIMO_CARACTERES,
    }
    return render(request, 'informes/montaje/inicio.html', context)