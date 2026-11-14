"""SISTRA-01 · Montaje de propuesta – Trabajo Social: vistas.

Solo el responsable de este requisito edita este archivo.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.parametrizacion.models import EstadoPeriodo, PeriodoAcademico, VersionPlantilla
from apps.personas.models import DirectorCarrera, EstadoInscripcion, Estudiante
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.forms.montaje import (
    CAMPOS_OBLIGATORIOS_ENVIO,
    ESTADOS_EDITABLES,
    MSG_01_01,
    MSG_01_02,
    MSG_01_03,
    MSG_01_07,
    MSG_01_08,
    CargaPlantillaWordForm,
    PropuestaMontajeForm,
)
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.propuestas.services.montaje import (
    PlantillaInvalidaError,
    extraer_datos_plantilla,
)
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion


def _obtener_proceso_estudiante(usuario):
    """Localiza el Proceso de Trabajo Social activo del estudiante autenticado.

    Raises PermissionDenied si el usuario no tiene perfil de estudiante.
    """
    estudiante = getattr(usuario, 'estudiante', None)
    if not estudiante:
        raise PermissionDenied

    inscripcion_activa = estudiante.inscripciones.filter(
        estado=EstadoInscripcion.ACTIVO
    ).select_related('carrera').first()

    if not inscripcion_activa:
        return None

    return getattr(inscripcion_activa, 'proceso', None)


def _calcular_avance_propuesta(propuesta) -> int:
    """Calcula el porcentaje de avance (0-100 %) según campos obligatorios diligenciados."""
    if not propuesta:
        return 0
    llenos = 0
    for campo in CAMPOS_OBLIGATORIOS_ENVIO:
        val = getattr(propuesta, campo, None)
        if val is not None and str(val).strip():
            llenos += 1
    return round(100 * llenos / len(CAMPOS_OBLIGATORIOS_ENVIO)) if CAMPOS_OBLIGATORIOS_ENVIO else 0


def _obtener_director_carrera(carrera):
    """Devuelve la asignación activa del Director de la carrera."""
    if not carrera:
        return None
    return DirectorCarrera.objects.filter(
        carrera=carrera, activo=True
    ).select_related('director__usuario').first()


def _registrar_auditoria(usuario, accion, resultado, id_registro=None, detalle=''):
    """Crea una fila en Auditoria. No captura excepciones: si falla, se propaga."""
    Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tabla_afectada='propuesta',
        id_registro_afectado=id_registro,
        detalle=detalle,
        resultado=resultado,
        fecha_hora=timezone.now(),
    )


@login_required
@require_http_methods(['GET', 'POST'])
def inicio(request):
    """Vista principal para registro, importación de Word y envío de propuesta."""
    # Lanza PermissionDenied (403) si el usuario no es estudiante
    proceso = _obtener_proceso_estudiante(request.user)

    if not proceso:
        return render(
            request,
            'propuestas/montaje/inicio.html',
            {
                'sin_proceso': True,
                'mensaje_sin_proceso': (
                    'No tienes un proceso de Trabajo Social activo asignado actualmente. '
                    'Por favor contacta al Director de tu carrera.'
                ),
            },
        )

    # Buscar la propuesta activa (no archivada y no rechazada definitivamente)
    propuesta = Propuesta.objects.filter(
        proceso=proceso, archivada=False
    ).exclude(estado=EstadoTramite.RECHAZADO).first()

    # -----------------------------------------------------------------
    # POST
    # -----------------------------------------------------------------
    if request.method == 'POST':
        accion = request.POST.get('accion', 'guardar')

        # 1. Importación desde plantilla Word (.docx) ─────────────────
        if accion == 'importar_word':
            if propuesta and propuesta.estado not in ESTADOS_EDITABLES:
                messages.error(request, 'La propuesta está en revisión y no admite importaciones.')
                return redirect('propuestas:montaje')

            word_form = CargaPlantillaWordForm(request.POST, request.FILES)
            if word_form.is_valid():
                try:
                    datos_extraidos, avisos = extraer_datos_plantilla(word_form.cleaned_data['archivo'])
                    for aviso in avisos:
                        messages.warning(request, aviso)

                    _registrar_auditoria(
                        request.user, 'Cargar plantilla', 'Éxito',
                        id_registro=propuesta.pk if propuesta else None,
                        detalle=f'Se leyeron {len(datos_extraidos)} campos.',
                    )

                    initial_data = {}
                    if propuesta:
                        for c in CAMPOS_OBLIGATORIOS_ENVIO:
                            initial_data[c] = getattr(propuesta, c, '')
                    initial_data.update(datos_extraidos)
                    form = PropuestaMontajeForm(initial=initial_data, instance=propuesta)
                    messages.success(
                        request,
                        f'Se autocompletaron {len(datos_extraidos)} campo(s) desde la plantilla Word. '
                        'Revisa la información y pulsa «Guardar borrador».',
                    )
                except PlantillaInvalidaError as err:
                    _registrar_auditoria(
                        request.user, 'Cargar plantilla', 'Fallo',
                        id_registro=propuesta.pk if propuesta else None,
                        detalle=str(err),
                    )
                    messages.error(request, MSG_01_03)
                    form = PropuestaMontajeForm(instance=propuesta)
            else:
                for err in word_form.errors.get('archivo', []):
                    messages.error(request, err)
                form = PropuestaMontajeForm(instance=propuesta)

            return render(
                request,
                'propuestas/montaje/inicio.html',
                {
                    'form': form,
                    'propuesta': propuesta,
                    'word_form': word_form,
                    'progreso': form.calcular_avance(),
                    'bloqueado': form.bloqueado,
                    'carrera': proceso.estudiante_carrera.carrera,
                },
            )

        # 2. Guardar borrador o Enviar a revisión ─────────────────────
        if propuesta and propuesta.estado not in ESTADOS_EDITABLES:
            # Auditoría de intento bloqueado
            _registrar_auditoria(
                request.user, 'Editar propuesta', 'Bloqueado',
                id_registro=propuesta.pk,
                detalle=f'Intento de {accion} en estado {propuesta.estado}.',
            )
            messages.error(request, 'La propuesta está en revisión y no admite modificaciones.')
            return redirect('propuestas:montaje')

        form = PropuestaMontajeForm(request.POST, instance=propuesta, accion=accion)

        if form.is_valid():
            try:
                with transaction.atomic():
                    instancia = form.save(commit=False)
                    es_nueva = not instancia.pk

                    if es_nueva:
                        # Verificar propuesta activa existente (EX-03)
                        if Propuesta.objects.filter(proceso=proceso, archivada=False).exclude(
                            estado=EstadoTramite.RECHAZADO
                        ).exists():
                            messages.error(request, MSG_01_08)
                            return render(
                                request, 'propuestas/montaje/inicio.html',
                                {
                                    'form': form,
                                    'propuesta': propuesta,
                                    'word_form': CargaPlantillaWordForm(),
                                    'progreso': form.calcular_avance(),
                                    'bloqueado': False,
                                    'carrera': proceso.estudiante_carrera.carrera,
                                },
                            )

                        # Periodo vigente — sin fallback
                        periodo_activo = PeriodoAcademico.objects.filter(
                            estado=EstadoPeriodo.VIGENTE
                        ).order_by('-fecha_inicio').first()
                        if not periodo_activo:
                            messages.error(
                                request,
                                'No hay un periodo académico vigente. Comunícate con tu Director.',
                            )
                            return render(
                                request, 'propuestas/montaje/inicio.html',
                                {
                                    'form': form,
                                    'propuesta': propuesta,
                                    'word_form': CargaPlantillaWordForm(),
                                    'progreso': form.calcular_avance(),
                                    'bloqueado': False,
                                    'carrera': proceso.estudiante_carrera.carrera,
                                },
                            )

                        instancia.proceso = proceso
                        instancia.periodo_academico = periodo_activo
                        instancia.codigo = f'PROP-{proceso.pk}-{int(timezone.now().timestamp())}'
                        instancia.estado = EstadoTramite.BORRADOR

                        # Versión de plantilla vigente
                        instancia.version_plantilla = VersionPlantilla.objects.filter(
                            plantilla__tipo='propuesta',
                            plantilla__estado='Activo',
                            es_vigente=True,
                        ).first()

                    estado_anterior = instancia.estado

                    # Acción: Enviar a revisión
                    if accion == 'enviar':
                        es_reenvio = estado_anterior == EstadoTramite.REQUIERE_MODIFICACION
                        instancia.estado = EstadoTramite.EN_REVISION
                        instancia.fecha_envio = timezone.now()
                        instancia.save()

                        HistorialEstado.objects.create(
                            propuesta=instancia,
                            usuario=request.user,
                            estado_anterior=estado_anterior,
                            estado_nuevo=EstadoTramite.EN_REVISION,
                            observacion='Propuesta enviada por el estudiante para revisión.',
                            tipo_accion='Envío',
                        )

                        _registrar_auditoria(
                            request.user,
                            'Reenviar propuesta' if es_reenvio else 'Enviar propuesta',
                            'Éxito',
                            id_registro=instancia.pk,
                            detalle=f'Estado anterior: {estado_anterior}.',
                        )

                        # Notificación al Director de Carrera
                        dir_carrera = _obtener_director_carrera(proceso.estudiante_carrera.carrera)
                        if dir_carrera and dir_carrera.director and dir_carrera.director.usuario:
                            Notificacion.objects.create(
                                usuario=dir_carrera.director.usuario,
                                propuesta=instancia,
                                tipo='Propuesta enviada',
                                mensaje=(
                                    f'El estudiante {request.user.nombre} ha enviado la propuesta '
                                    f'«{instancia.titulo}» para su revisión.'
                                ),
                            )

                        messages.success(request, MSG_01_02)
                    else:
                        # Guardar borrador
                        instancia.save()
                        _registrar_auditoria(
                            request.user,
                            'Crear propuesta' if es_nueva else 'Guardar borrador',
                            'Éxito',
                            id_registro=instancia.pk,
                        )
                        messages.success(request, MSG_01_01)

            except IntegrityError:
                messages.error(request, MSG_01_07)
                return render(
                    request, 'propuestas/montaje/inicio.html',
                    {
                        'form': form,
                        'propuesta': propuesta,
                        'word_form': CargaPlantillaWordForm(),
                        'progreso': form.calcular_avance(),
                        'bloqueado': False,
                        'carrera': proceso.estudiante_carrera.carrera,
                    },
                )

            return redirect('propuestas:montaje')
        else:
            messages.error(request, 'Corrige los errores señalados en el formulario.')

    # -----------------------------------------------------------------
    # GET
    # -----------------------------------------------------------------
    else:
        form = PropuestaMontajeForm(instance=propuesta)

    progreso = _calcular_avance_propuesta(propuesta) if propuesta else form.calcular_avance()
    bloqueado = bool(propuesta and propuesta.estado not in ESTADOS_EDITABLES)

    # Observaciones si la propuesta viene de 'Requiere modificación'
    observacion_director = ''
    if propuesta and propuesta.estado == EstadoTramite.REQUIERE_MODIFICACION:
        ultimo_historial = HistorialEstado.objects.filter(
            propuesta=propuesta, estado_nuevo=EstadoTramite.REQUIERE_MODIFICACION
        ).order_by('-fecha_hora').first()
        if ultimo_historial:
            observacion_director = ultimo_historial.observacion

    return render(
        request,
        'propuestas/montaje/inicio.html',
        {
            'form': form,
            'propuesta': propuesta,
            'word_form': CargaPlantillaWordForm(),
            'progreso': progreso,
            'bloqueado': bloqueado,
            'observacion_director': observacion_director,
            'carrera': proceso.estudiante_carrera.carrera,
        },
    )
