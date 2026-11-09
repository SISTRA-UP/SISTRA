"""SISTRA-02 · Aprobación de propuesta: vistas y controladores web.

Solo el responsable de este requisito edita este archivo.
Implementa:
- Bandeja de entrada del Director con filtros, paginación y prefetching sin N+1.
- Restricción de acceso por asignación de carrera activa (DirectorCarrera activo).
- Exclusión estricta de borradores (RN-02-01).
- Endpoints delgados de decisión individual y masiva delegando a los formularios.
- Bloqueo de transición desde Rechazado sin modal de reactivación.
- Endpoint de detalle modal lazy en formato JSON.
- Descarga segura de documento de propuesta en PDF.
"""

from datetime import timedelta
import json
from pathlib import Path
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.informes.models import Informe
from apps.parametrizacion.models import TipoRechazo
from apps.personas.models import DirectorCarrera
from apps.propuestas.forms.aprobacion import (
    DIAS_SEMAFORO_AMARILLO,
    DIAS_SEMAFORO_VERDE,
    MSG_02_01,
    MSG_02_02,
    MSG_02_03,
    MSG_02_04,
    MSG_02_07,
    AprobacionPropuestaForm,
    FiltroBandejaPropuestasForm,
    ModificacionPropuestaForm,
    PropuestaBloqueadaError,
    ReactivacionInvalidaError,
    ReactivacionPropuestaForm,
    RechazoPropuestaForm,
    calcular_semaforo,
    puede_revertir_aprobacion,
)
from apps.propuestas.forms.aprobacion_masiva import AccionMasivaForm
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import HistorialEstado
from apps.usuarios.models import Estado

ELEMENTOS_POR_PAGINA = 10


def _carrera_activa_del_director(usuario) -> DirectorCarrera | None:
    """Obtiene la asignación de carrera activa del Director autenticado (RN-10-04).

    No se restringe por nombre textual de rol para permitir compatibilidad con
    roles dinámicos creados por ADMO (p. ej. Decano o Coordinador).
    """
    if not usuario.is_authenticated:
        return None
    return (
        DirectorCarrera.objects.filter(director__usuario=usuario, activo=True)
        .select_related('carrera', 'director')
        .order_by('-fecha_inicio', '-id_director_carrera')
        .first()
    )


@login_required
@require_GET
def bandeja(request: HttpRequest) -> HttpResponse:
    """Bandeja principal de propuestas asignadas a la carrera activa del Director."""
    asignacion = _carrera_activa_del_director(request.user)
    if not asignacion:
        messages.warning(
            request,
            'No tienes asignada una carrera activa como Director en este momento.',
        )
        return render(
            request,
            'propuestas/aprobacion/bandeja.html',
            {
                'asignacion': None,
                'propuestas_con_meta': [],
                'form_filtro': FiltroBandejaPropuestasForm(),
                'total_propuestas': 0,
            },
        )

    form_filtro = FiltroBandejaPropuestasForm(request.GET)
    carrera = asignacion.carrera

    # RN-02-01: Excluir borradores inmutables de los estudiantes
    propuestas_qs = (
        Propuesta.objects.filter(
            proceso__estudiante_carrera__carrera=carrera,
            archivada=False,
        )
        .exclude(estado=EstadoTramite.BORRADOR)
        .select_related(
            'proceso__estudiante_carrera__estudiante__usuario',
            'proceso__estudiante_carrera__carrera',
            'periodo_academico',
            'version_plantilla',
        )
        .order_by('-fecha_envio', '-fecha_creacion')
    )

    if form_filtro.is_valid():
        buscar = form_filtro.cleaned_data.get('buscar')
        estado = form_filtro.cleaned_data.get('estado')
        semaforo_filtro = form_filtro.cleaned_data.get('semaforo')

        if buscar:
            propuestas_qs = propuestas_qs.filter(
                Q(titulo__icontains=buscar)
                | Q(codigo__icontains=buscar)
                | Q(proceso__estudiante_carrera__estudiante__usuario__nombre__icontains=buscar)
                | Q(proceso__estudiante_carrera__estudiante__usuario__cedula__icontains=buscar)
            )

        if estado:
            propuestas_qs = propuestas_qs.filter(estado=estado)

        if semaforo_filtro:
            ahora = timezone.now()
            # El semáforo solo corre en 'En revisión'
            propuestas_qs = propuestas_qs.filter(estado=EstadoTramite.EN_REVISION)
            limite_verde = ahora - timedelta(days=DIAS_SEMAFORO_VERDE)
            limite_amarillo = ahora - timedelta(days=DIAS_SEMAFORO_AMARILLO)

            if semaforo_filtro == 'verde':
                propuestas_qs = propuestas_qs.filter(fecha_envio__gte=limite_verde)
            elif semaforo_filtro == 'amarillo':
                propuestas_qs = propuestas_qs.filter(
                    fecha_envio__lt=limite_verde, fecha_envio__gte=limite_amarillo
                )
            elif semaforo_filtro == 'rojo':
                propuestas_qs = propuestas_qs.filter(fecha_envio__lt=limite_amarillo)

    total_filtradas = propuestas_qs.count()

    paginador = Paginator(propuestas_qs, ELEMENTOS_POR_PAGINA)
    numero_pagina = request.GET.get('page')
    pagina_obj = paginador.get_page(numero_pagina)
    propuestas_pagina = list(pagina_obj.object_list)

    ids_aprobadas = [p.pk for p in propuestas_pagina if p.estado == EstadoTramite.APROBADO]
    cargues_bloqueados_ids = set()
    informes_bloqueados_ids = set()

    if ids_aprobadas:
        cargues_bloqueados_ids = set(
            CargueUp.objects.filter(
                propuesta_id__in=ids_aprobadas,
                estado_verificacion__in=[
                    EstadoVerificacion.PENDIENTE,
                    EstadoVerificacion.APROBADO_EN_UP,
                ],
            ).values_list('propuesta_id', flat=True)
        )
        informes_bloqueados_ids = set(
            Informe.objects.filter(propuesta_id__in=ids_aprobadas).values_list(
                'propuesta_id', flat=True
            )
        )

    propuestas_con_meta = []
    for prop in propuestas_pagina:
        bloqueada_reversion = (
            prop.pk in cargues_bloqueados_ids or prop.pk in informes_bloqueados_ids
        )
        sem = calcular_semaforo(prop)
        propuestas_con_meta.append(
            {
                'propuesta': prop,
                'semaforo': sem,
                'bloqueada_reversion': bloqueada_reversion,
                'bloqueo_motivo': MSG_02_07 if bloqueada_reversion else '',
            }
        )

    tipos_rechazo = TipoRechazo.objects.filter(estado=Estado.ACTIVO).order_by('nombre')

    contexto = {
        'asignacion': asignacion,
        'carrera': carrera,
        'form_filtro': form_filtro,
        'pagina_obj': pagina_obj,
        'propuestas_con_meta': propuestas_con_meta,
        'total_propuestas': total_filtradas,
        'tipos_rechazo': tipos_rechazo,
        'form_aprobar': AprobacionPropuestaForm(),
        'form_modificar': ModificacionPropuestaForm(),
        'form_rechazar': RechazoPropuestaForm(),
        'form_reactivar': ReactivacionPropuestaForm(),
        'form_masivo': AccionMasivaForm(),
        'EstadoTramite': EstadoTramite,
    }
    return render(request, 'propuestas/aprobacion/bandeja.html', contexto)


@login_required
@require_GET
def detalle_propuesta(request: HttpRequest, id_propuesta: int) -> JsonResponse:
    """Endpoint JSON lazy para cargar la información detallada e historial de una propuesta."""
    asignacion = _carrera_activa_del_director(request.user)
    if not asignacion:
        return JsonResponse({'error': 'Sin permisos de Director activo.'}, status=403)

    propuesta = get_object_or_404(
        Propuesta.objects.select_related(
            'proceso__estudiante_carrera__estudiante__usuario',
            'proceso__estudiante_carrera__carrera',
            'periodo_academico',
            'version_plantilla',
        ).prefetch_related('historial__usuario', 'historial__tipo_rechazo', 'cronograma'),
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    estudiante_usuario = propuesta.proceso.estudiante_carrera.estudiante.usuario
    semaforo = calcular_semaforo(propuesta)
    puede_revertir, motivo_bloqueo = puede_revertir_aprobacion(propuesta)

    historial_qs = (
        HistorialEstado.objects.filter(propuesta=propuesta)
        .select_related('usuario', 'tipo_rechazo')
        .order_by('-fecha_hora')
    )
    historial_lista = []
    for h in historial_qs:
        historial_lista.append(
            {
                'fecha_hora': timezone.localtime(h.fecha_hora).strftime('%d/%m/%Y %H:%M'),
                'usuario': h.usuario.nombre,
                'tipo_accion': h.tipo_accion,
                'estado_anterior': h.estado_anterior or 'N/A',
                'estado_nuevo': h.estado_nuevo,
                'tipo_rechazo': h.tipo_rechazo.nombre if h.tipo_rechazo else '',
                'observacion': h.observacion or '',
                'motivo_reactivacion': h.motivo_reactivacion or '',
            }
        )

    tiene_doc = bool(propuesta.version_plantilla and propuesta.version_plantilla.ruta_archivo)
    programa_estudiante = (
        propuesta.proceso.estudiante_carrera.carrera.nombre
        if propuesta.proceso and propuesta.proceso.estudiante_carrera and propuesta.proceso.estudiante_carrera.carrera
        else 'No registrado'
    )
    datos = {
        'id_propuesta': propuesta.pk,
        'codigo': propuesta.codigo,
        'titulo': propuesta.titulo,
        'estado': propuesta.estado,
        'programa': programa_estudiante,
        'fecha_envio': (
            timezone.localtime(propuesta.fecha_envio).strftime('%d/%m/%Y %H:%M')
            if propuesta.fecha_envio
            else 'Sin envío'
        ),
        'semaforo': semaforo,
        'puede_revertir': puede_revertir,
        'motivo_bloqueo': motivo_bloqueo,
        'estudiante': {
            'nombre': estudiante_usuario.nombre,
            'cedula': estudiante_usuario.cedula,
            'correo': estudiante_usuario.correo_institucional,
            'programa': programa_estudiante,
        },
        'periodo': (
            propuesta.periodo_academico.nombre
            if propuesta.periodo_academico
            else 'No especificado'
        ),
        'entidad': propuesta.entidad or 'No especificada',
        'sector_entidad': propuesta.sector_entidad or 'No especificado',
        'poblacion_beneficiada': propuesta.poblacion_beneficiada or '',
        'justificacion': propuesta.justificacion or '',
        'objetivos': propuesta.objetivos or '',
        'resena_historica': propuesta.resena_historica or '',
        'identificacion_necesidad': propuesta.identificacion_necesidad or '',
        'referente_teorico': propuesta.referente_teorico or '',
        'impacto_social': propuesta.impacto_social or '',
        'identificacion_poblacion': propuesta.identificacion_poblacion or '',
        'propuesta_social': propuesta.propuesta_social or '',
        'zona': propuesta.zona or 'No registrada',
        'area': propuesta.area or 'No registrada',
        'sector': propuesta.sector or 'No registrado',
        'unidad': propuesta.unidad or 'No registrada',
        'fecha_inicio': (
            propuesta.fecha_inicio.strftime('%d/%m/%Y')
            if propuesta.fecha_inicio
            else ''
        ),
        'fecha_fin': (
            propuesta.fecha_fin.strftime('%d/%m/%Y')
            if propuesta.fecha_fin
            else ''
        ),
        'tiene_documento': tiene_doc,
        'cronograma': [
            {
                'orden': a.orden,
                'nombre': a.nombre,
                'descripcion': a.descripcion,
                'fecha_inicio': a.fecha_inicio.strftime('%d/%m/%Y') if a.fecha_inicio else '',
                'fecha_fin': a.fecha_fin.strftime('%d/%m/%Y') if a.fecha_fin else '',
                'responsable': a.responsable,
            }
            for a in propuesta.cronograma.all()
        ],
        'historial': historial_lista,
    }
    return JsonResponse(datos)


@login_required
@require_POST
def cambiar_estado(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Aplica una decisión individual: Aprobar, Requiere modificación o Rechazar."""
    asignacion = _carrera_activa_del_director(request.user)
    if not asignacion:
        messages.error(request, 'No tienes permisos de Director activo.')
        return redirect('propuestas:aprobacion')

    propuesta = get_object_or_404(
        Propuesta.objects.select_related(
            'proceso__estudiante_carrera__estudiante__usuario'
        ),
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    if propuesta.estado not in [EstadoTramite.EN_REVISION, EstadoTramite.APROBADO]:
        if propuesta.estado == EstadoTramite.RECHAZADO:
            messages.error(
                request,
                'Una propuesta rechazada solo puede ser reactivada mediante el modal de reactivación justificando el motivo.',
            )
        else:
            messages.error(
                request,
                f"Solo se puede decidir sobre propuestas en estado 'En revisión' o 'Aprobado' (estado actual: {propuesta.estado}).",
            )
        return redirect('propuestas:aprobacion')

    if propuesta.estado == EstadoTramite.APROBADO:
        puede, motivo = puede_revertir_aprobacion(propuesta)
        if not puede:
            messages.error(request, motivo)
            return redirect('propuestas:aprobacion')

    nuevo_estado = request.POST.get('nuevo_estado', '').strip()

    try:
        if nuevo_estado == EstadoTramite.APROBADO:
            form = AprobacionPropuestaForm(request.POST)
            if not form.is_valid():
                for error in form.errors.values():
                    messages.error(request, error)
                return redirect('propuestas:aprobacion')
            form.procesar(propuesta, request.user)
            messages.success(request, MSG_02_01)

        elif nuevo_estado == EstadoTramite.REQUIERE_MODIFICACION:
            form = ModificacionPropuestaForm(request.POST)
            if not form.is_valid():
                for error in form.errors.values():
                    messages.error(request, error)
                return redirect('propuestas:aprobacion')
            form.procesar(propuesta, request.user)
            messages.success(request, MSG_02_02)

        elif nuevo_estado == EstadoTramite.RECHAZADO:
            form = RechazoPropuestaForm(request.POST)
            if not form.is_valid():
                for error in form.errors.values():
                    messages.error(request, error)
                return redirect('propuestas:aprobacion')
            form.procesar(propuesta, request.user)
            messages.success(request, MSG_02_03)

        else:
            messages.error(request, 'El estado seleccionado no es válido.')

    except PropuestaBloqueadaError as e:
        messages.error(request, str(e))
    except ValidationError as e:
        messages.error(request, e.message if hasattr(e, 'message') else str(e))
    except Exception:
        messages.error(
            request,
            'No fue posible procesar la decisión sobre la propuesta. Por favor, inténtalo nuevamente.',
        )

    return redirect('propuestas:aprobacion')


@login_required
@require_POST
def reactivar_propuesta(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Aplica la reactivación de una propuesta rechazada por error (RG-04 / EX-02)."""
    asignacion = _carrera_activa_del_director(request.user)
    if not asignacion:
        messages.error(request, 'No tienes permisos de Director activo.')
        return redirect('propuestas:aprobacion')

    propuesta = get_object_or_404(
        Propuesta.objects.select_related(
            'proceso__estudiante_carrera__estudiante__usuario'
        ),
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    form = ReactivacionPropuestaForm(request.POST)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, error)
        return redirect('propuestas:aprobacion')

    try:
        form.procesar(propuesta, request.user)
        messages.success(request, MSG_02_04)
    except ReactivacionInvalidaError as e:
        messages.error(request, str(e))
    except ValidationError as e:
        messages.error(request, e.message if hasattr(e, 'message') else str(e))
    except Exception:
        messages.error(
            request,
            'No fue posible reactivar la propuesta. Por favor, inténtalo nuevamente.',
        )

    return redirect('propuestas:aprobacion')


@login_required
@require_POST
def accion_masiva(request: HttpRequest) -> HttpResponse:
    """Aplica la acción en lote (Aprobar, Rechazar o Reactivar masivo)."""
    asignacion = _carrera_activa_del_director(request.user)
    if not asignacion:
        messages.error(request, 'No tienes permisos de Director activo.')
        return redirect('propuestas:aprobacion')

    form = AccionMasivaForm(request.POST)
    if not form.is_valid():
        for error in form.errors.values():
            messages.error(request, error)
        return redirect('propuestas:aprobacion')

    try:
        procesadas = form.procesar(asignacion.carrera, request.user)
        messages.success(
            request,
            f'Se procesaron exitosamente {procesadas} propuesta(s) de forma masiva.',
        )
    except (ReactivacionInvalidaError, ValidationError) as e:
        messages.error(request, str(e))
    except Exception:
        messages.error(
            request,
            'No fue posible completar la acción masiva. Por favor, inténtalo nuevamente.',
        )

    return redirect('propuestas:aprobacion')


@login_required
@require_GET
def descargar_documento(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Permite previsualizar o descargar el documento adjunto de la propuesta."""
    asignacion = _carrera_activa_del_director(request.user)
    if not asignacion:
        raise Http404('Permiso denegado.')

    propuesta = get_object_or_404(
        Propuesta,
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    if not (propuesta.version_plantilla and propuesta.version_plantilla.ruta_archivo):
        raise Http404('La propuesta no cuenta con documento adjunto.')

    ruta = Path(propuesta.version_plantilla.ruta_archivo)
    if not ruta.is_file():
        raise Http404('El archivo solicitado no se encuentra en el servidor.')

    try:
        archivo = open(ruta, 'rb')
        response = FileResponse(archivo, content_type='application/octet-stream')
        nombre = propuesta.version_plantilla.nombre_archivo or ruta.name
        response['Content-Disposition'] = f'inline; filename="{nombre}"'
        return response
    except Exception:
        raise Http404('El archivo solicitado no se encuentra en el servidor.')
