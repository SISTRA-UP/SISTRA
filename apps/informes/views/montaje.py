"""Vistas de montaje de informe (SISTRA-06).

Permite al estudiante registrar su informe de Trabajo Social,
guardarlo como borrador y enviarlo a revisión.

Preparado para integrarse con SISTRA-07 (Aprobación de informe) de Edwin.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.informes.forms.montaje import InformeForm
from apps.informes.models import Informe
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import HistorialEstado, Notificacion


def _calcular_avance(informe):
    """Calcula el % de avance a partir de un objeto informe (o datos dict)."""
    campos = ['resultados', 'conclusiones', 'recomendaciones']
    llenos = 0
    for campo in campos:
        if isinstance(informe, dict):
            valor = informe.get(campo, '') or ''
        else:
            valor = getattr(informe, campo, '') or ''
        if valor.strip():
            llenos += 1
    return int((llenos / len(campos)) * 100)


@login_required
# TODO: Agregar @permission_required('informes.montar_informe', raise_exception=True) cuando se asignen los permisos en SISTRA-10
def inicio(request):
    """Vista principal de montaje de informe."""
    usuario = request.user

    # --- Validación de acceso: debe ser estudiante ---
    from apps.personas.models import Estudiante
    try:
        estudiante = Estudiante.objects.get(usuario=usuario)
    except Estudiante.DoesNotExist:
        return render(request, 'informes/montaje/inicio.html', {
            'sin_acceso': True,
            'mensaje_error': 'No tienes un perfil de estudiante registrado en el sistema.',
        })

    # --- Validación de acceso: debe tener propuesta APROBADO EN UP ---
    propuesta = Propuesta.objects.filter(
        proceso__estudiante_carrera__estudiante=estudiante,
        estado=EstadoTramite.APROBADO_EN_UP,
        archivada=False,
    ).first()

    if not propuesta:
        return render(request, 'informes/montaje/inicio.html', {
            'sin_acceso': True,
            'mensaje_error': (
                'No tienes una propuesta en estado "Aprobado en UP". '
                'Debes completar el proceso de propuesta antes de montar el informe.'
            ),
        })

    # --- Obtener o crear el informe ---
    informe = Informe.objects.filter(propuesta=propuesta).first()
    if not informe:
        informe = Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=propuesta.periodo_academico,
            codigo=f'INF-{propuesta.codigo.replace("PROP-", "")}',
            estado=EstadoTramite.BORRADOR,
        )

    # --- Determinar si está bloqueado ---
    estados_bloqueados = [
        EstadoTramite.EN_REVISION,
        EstadoTramite.APROBADO,
        EstadoTramite.SUBIDO_EN_UP,
        EstadoTramite.APROBADO_EN_UP,
    ]
    bloqueado = informe.estado in estados_bloqueados

    # --- Observación del Director (SISTRA-07 de Edwin) ---
    ultima_observacion = None
    if informe.estado == EstadoTramite.REQUIERE_MODIFICACION:
        ultima_observacion = HistorialEstado.objects.filter(
            informe=informe,
            estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION,
        ).order_by('-fecha_hora').first()

    # --- Manejo de POST ---
    if request.method == 'POST':
        form = InformeForm(request.POST, instance=informe)
        if form.is_valid():
            accion = request.POST.get('accion')
            estado_anterior = informe.estado

            # ⚠️ CORRECCIÓN: recalcular avance con los datos POST, no con los viejos.
            avance_post = _calcular_avance(form.cleaned_data)

            if accion == 'guardar_borrador':
                informe = form.save(commit=False)
                informe.estado = EstadoTramite.BORRADOR
                informe.save()

                if estado_anterior != EstadoTramite.BORRADOR:
                    HistorialEstado.objects.create(
                        informe=informe,
                        usuario=usuario,
                        estado_anterior=estado_anterior,
                        estado_nuevo=EstadoTramite.BORRADOR,
                        tipo_accion='guardar_borrador',
                        fecha_hora=timezone.now(),
                    )

                messages.success(request, 'Borrador guardado exitosamente.')
                return redirect('informes:montaje')

            elif accion == 'enviar':
                if avance_post < 100:
                    messages.error(
                        request,
                        'Debes completar los 3 campos (100% de avance) para enviar el informe.'
                    )
                else:
                    informe = form.save(commit=False)
                    informe.estado = EstadoTramite.EN_REVISION
                    informe.fecha_envio = timezone.now()

                    # ⬅️ NUEVO: Aumentar versión si es una reentrega (corrección del Director)
                    if estado_anterior == EstadoTramite.REQUIERE_MODIFICACION:
                        informe.version_entrega += 1

                    informe.save()

                    # Registrar en historial de estados
                    HistorialEstado.objects.create(
                        informe=informe,
                        usuario=usuario,
                        estado_anterior=estado_anterior,
                        estado_nuevo=EstadoTramite.EN_REVISION,
                        tipo_accion='envio_informe',
                        fecha_hora=timezone.now(),
                    )

                    # Crear notificación al Director (preparado para SISTRA-07 de Edwin)
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

                    messages.success(
                        request,
                        'Informe enviado a revisión exitosamente. '
                        'El Director será notificado.'
                    )
                    return redirect('informes:montaje')
    else:
        form = InformeForm(instance=informe)

    # --- Avance actualizado (post-guardado) para renderizar ---
    informe.refresh_from_db()
    avance = _calcular_avance(informe)

    # --- Clases de Bootstrap para el estado inicial (al cargar la página) ---
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
    }
    return render(request, 'informes/montaje/inicio.html', context)