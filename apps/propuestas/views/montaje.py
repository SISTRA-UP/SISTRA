"""SISTRA-01 · Montaje de propuesta – Trabajo Social: vistas.

Solo el responsable de este requisito edita este archivo.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.parametrizacion.models import EstadoPeriodo, PeriodoAcademico
from apps.personas.models import DirectorCarrera, EstadoInscripcion, Estudiante
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.forms.montaje import (
    CAMPOS_OBLIGATORIOS_ENVIO,
    ESTADOS_EDITABLES,
    CargaPlantillaWordForm,
    PropuestaMontajeForm,
)
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.propuestas.services.montaje import (
    PlantillaInvalidaError,
    extraer_datos_plantilla,
)
from apps.seguimiento.models import HistorialEstado, Notificacion


def _obtener_proceso_estudiante(usuario):
    """Localiza el Proceso de Trabajo Social activo del estudiante autenticado."""
    estudiante = getattr(usuario, 'estudiante', None)
    if not estudiante:
        # Si es superusuario o admin probando, busca si existe algún proceso
        if usuario.is_superuser:
            return ProcesoTrabajoSocial.objects.select_related(
                'estudiante_carrera__estudiante__usuario',
                'estudiante_carrera__carrera',
            ).first()
        return None

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


@login_required
@require_http_methods(['GET', 'POST'])
def inicio(request):
    """Vista principal para registro, autoguardado, importación de Word y envío de propuesta."""
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

    es_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # -------------------------------------------------------------
    # POST
    # -------------------------------------------------------------
    if request.method == 'POST':
        accion = request.POST.get('accion', 'guardar')

        # 1. Importación desde plantilla Word (.docx)
        if accion == 'importar_word':
            if propuesta and propuesta.estado not in ESTADOS_EDITABLES:
                messages.error(request, 'La propuesta está en revisión y no admite importaciones.')
                return redirect('propuestas:montaje')

            word_form = CargaPlantillaWordForm(request.POST, request.FILES)
            if word_form.is_valid():
                try:
                    datos_extraidos = extraer_datos_plantilla(word_form.cleaned_data['archivo'])
                    if not datos_extraidos:
                        messages.warning(request, 'No se reconocieron etiquetas válidas en el archivo Word cargado.')
                        form = PropuestaMontajeForm(instance=propuesta)
                    else:
                        # Prellenar formulario con los datos extraídos
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
                    messages.error(request, str(err))
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

        # 2. Guardar borrador, Autoguardar o Enviar a revisión
        if propuesta and propuesta.estado not in ESTADOS_EDITABLES:
            if es_ajax:
                return JsonResponse({'ok': False, 'error': 'La propuesta está bloqueada para edición.'}, status=403)
            messages.error(request, 'La propuesta está en revisión y no admite modificaciones.')
            return redirect('propuestas:montaje')

        form = PropuestaMontajeForm(request.POST, instance=propuesta, accion=accion)

        if form.is_valid():
            with transaction.atomic():
                instancia = form.save(commit=False)

                # Si es una nueva propuesta, vincular proceso, periodo y código único
                if not instancia.pk:
                    instancia.proceso = proceso
                    periodo_activo = PeriodoAcademico.objects.filter(
                        estado=EstadoPeriodo.VIGENTE
                    ).order_by('-fecha_inicio').first() or PeriodoAcademico.objects.order_by('-fecha_inicio').first()
                    instancia.periodo_academico = periodo_activo
                    instancia.codigo = f'PROP-{proceso.pk}-{int(timezone.now().timestamp())}'
                    instancia.estado = EstadoTramite.BORRADOR

                estado_anterior = instancia.estado

                # Acción: Enviar a revisión
                if accion == 'enviar':
                    instancia.estado = EstadoTramite.EN_REVISION
                    instancia.fecha_envio = timezone.now()
                    instancia.save()

                    # Registro en Historial de Estados
                    HistorialEstado.objects.create(
                        propuesta=instancia,
                        usuario=request.user,
                        estado_anterior=estado_anterior,
                        estado_nuevo=EstadoTramite.EN_REVISION,
                        observacion='Propuesta enviada por el estudiante para revisión.',
                        tipo_accion='Envío',
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
                else:
                    # Guardar borrador / autoguardar
                    instancia.save()

            avance = _calcular_avance_propuesta(instancia)

            if es_ajax or accion == 'autoguardar':
                return JsonResponse({
                    'ok': True,
                    'progreso': avance,
                    'estado': instancia.estado,
                    'mensaje': 'Borrador guardado exitosamente.',
                })

            if accion == 'enviar':
                messages.success(
                    request,
                    '¡Tu propuesta ha sido enviada con éxito a revisión del Director de Carrera!',
                )
            else:
                messages.success(request, 'Borrador guardado correctamente.')

            return redirect('propuestas:montaje')
        else:
            if es_ajax:
                return JsonResponse({'ok': False, 'errores': form.errors}, status=400)
            messages.error(request, 'Corrige los errores señalados en el formulario.')

    # -------------------------------------------------------------
    # GET
    # -------------------------------------------------------------
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


@login_required
@require_POST
def autoguardar(request):
    """Endpoint JSON delegado para autoguardado asíncrono con fetch."""
    request.POST = request.POST.copy()
    request.POST['accion'] = 'autoguardar'
    return inicio(request)
