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
import mimetypes
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
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
    LONGITUD_MAXIMA_TEXTO,
    MSG_02_01,
    MSG_02_02,
    MSG_02_03,
    MSG_02_04,
    MSG_02_07,
    RESULTADO_BLOQUEADO,
    AprobacionPropuestaForm,
    FiltroBandejaPropuestasForm,
    ModificacionPropuestaForm,
    PropuestaBloqueadaError,
    ReactivacionInvalidaError,
    ReactivacionPropuestaForm,
    RechazoPropuestaForm,
    _auditar,
    anotar_ultima_decision,
    calcular_semaforo,
    obtener_limites_semaforo,
    puede_revertir_aprobacion,
    sanitizar_texto,
)
from apps.propuestas.forms.aprobacion_masiva import AccionMasivaForm
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import HistorialEstado
from apps.usuarios.models import Estado

ELEMENTOS_POR_PAGINA = 10
# Estados posteriores al cargue en UP: el Director ya no puede cambiar la decisión (RN-02-04).
ESTADOS_EN_UP = (EstadoTramite.SUBIDO_EN_UP, EstadoTramite.APROBADO_EN_UP)
MSG_BLOQUEO_REQUIERE_MODIFICACION = (
    'La propuesta espera las correcciones del estudiante; podrás decidir cuando la reenvíe.'
)
# Tope del estado solicitado que se copia a la auditoría de intentos bloqueados.
LONGITUD_MAXIMA_ESTADO = 50


def _mostrar_errores(request: HttpRequest, form) -> None:
    """Muestra cada error del formulario como texto plano (sin la lista HTML de Django)."""
    for errores in form.errors.values():
        for texto in errores:
            messages.error(request, texto)


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
        # Sin carrera activa como Director no hay acceso, igual que en el detalle.
        raise PermissionDenied

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

    limite_verde, limite_amarillo = obtener_limites_semaforo()

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
            corte_verde = ahora - timedelta(days=limite_verde)
            corte_amarillo = ahora - timedelta(days=limite_amarillo)

            if semaforo_filtro == 'verde':
                propuestas_qs = propuestas_qs.filter(fecha_envio__gte=corte_verde)
            elif semaforo_filtro == 'amarillo':
                propuestas_qs = propuestas_qs.filter(
                    fecha_envio__lt=corte_verde, fecha_envio__gte=corte_amarillo
                )
            elif semaforo_filtro == 'rojo':
                propuestas_qs = propuestas_qs.filter(fecha_envio__lt=corte_amarillo)

    total_filtradas = propuestas_qs.count()

    # Fecha de la última decisión anotada en la misma consulta de la página (sin N+1).
    paginador = Paginator(anotar_ultima_decision(propuestas_qs), ELEMENTOS_POR_PAGINA)
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

    limites_sem = (limite_verde, limite_amarillo)
    propuestas_con_meta = []
    for prop in propuestas_pagina:
        # El control solo queda activo donde el servidor acepta la decisión (cambiar_estado).
        if prop.estado == EstadoTramite.REQUIERE_MODIFICACION:
            motivo_bloqueo = MSG_BLOQUEO_REQUIERE_MODIFICACION
        elif prop.estado in ESTADOS_EN_UP or (
            prop.pk in cargues_bloqueados_ids or prop.pk in informes_bloqueados_ids
        ):
            motivo_bloqueo = MSG_02_07
        else:
            motivo_bloqueo = ''
        sem = calcular_semaforo(prop, limites=limites_sem)
        propuestas_con_meta.append(
            {
                'propuesta': prop,
                'semaforo': sem,
                'bloqueada_reversion': bool(motivo_bloqueo),
                'motivo_bloqueo': motivo_bloqueo,
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
        'limite_verde': limite_verde,
        'limite_amarillo': limite_amarillo,
        'limite_rojo': limite_amarillo + 1,
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
        raise PermissionDenied

    propuesta = get_object_or_404(
        Propuesta.objects.select_related(
            'proceso__estudiante_carrera__estudiante__usuario'
        ),
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    # Se quitan los NUL: PostgreSQL los rechaza al guardar el intento en auditoría.
    nuevo_estado = request.POST.get('nuevo_estado', '').replace('\x00', '').strip()

    motivo_bloqueo = ''
    if propuesta.estado == EstadoTramite.RECHAZADO:
        motivo_bloqueo = 'Una propuesta rechazada solo puede ser reactivada mediante el modal de reactivación justificando el motivo.'
    elif propuesta.estado != EstadoTramite.EN_REVISION:
        # Aprobado solo se bloquea si ya hay cargue en UP o informe (RN-02-04).
        motivo_bloqueo = (
            puede_revertir_aprobacion(propuesta)[1]
            if propuesta.estado == EstadoTramite.APROBADO
            else f"Solo se puede decidir sobre propuestas en estado 'En revisión' o 'Aprobado' (estado actual: {propuesta.estado})."
        )

    if motivo_bloqueo:
        # El BRD exige auditar también los intentos bloqueados. El POST llega sin validar:
        # se recorta antes de guardarlo y la causal solo se registra si existe.
        id_causal = request.POST.get('tipo_rechazo', '')
        causal = TipoRechazo.objects.filter(pk=id_causal).first() if id_causal.isdigit() else None
        _auditar(
            request.user,
            'CAMBIAR_ESTADO_BLOQUEADO',
            propuesta,
            estado_anterior=propuesta.estado,
            estado_nuevo=nuevo_estado[:LONGITUD_MAXIMA_ESTADO],
            tipo_rechazo=causal.nombre if causal else '',
            observacion=sanitizar_texto(request.POST.get('observacion', '').replace('\x00', ''))[:LONGITUD_MAXIMA_TEXTO],
            detalle_extra=motivo_bloqueo,
            resultado=RESULTADO_BLOQUEADO,
        )
        messages.error(request, motivo_bloqueo)
        return redirect('propuestas:aprobacion')

    try:
        if nuevo_estado == EstadoTramite.APROBADO:
            form = AprobacionPropuestaForm(request.POST)
            if not form.is_valid():
                _mostrar_errores(request, form)
                return redirect('propuestas:aprobacion')
            form.procesar(propuesta, request.user)
            messages.success(request, MSG_02_01)

        elif nuevo_estado == EstadoTramite.REQUIERE_MODIFICACION:
            form = ModificacionPropuestaForm(request.POST)
            if not form.is_valid():
                _mostrar_errores(request, form)
                return redirect('propuestas:aprobacion')
            form.procesar(propuesta, request.user)
            messages.success(request, MSG_02_02)

        elif nuevo_estado == EstadoTramite.RECHAZADO:
            form = RechazoPropuestaForm(request.POST)
            if not form.is_valid():
                _mostrar_errores(request, form)
                return redirect('propuestas:aprobacion')
            form.procesar(propuesta, request.user)
            messages.success(request, MSG_02_03)

        else:
            messages.error(request, 'El estado seleccionado no es válido.')

    except PropuestaBloqueadaError as e:
        messages.error(request, str(e))
    except ValidationError as e:
        messages.error(request, e.messages[0])
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
        raise PermissionDenied

    propuesta = get_object_or_404(
        Propuesta.objects.select_related(
            'proceso__estudiante_carrera__estudiante__usuario'
        ),
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    form = ReactivacionPropuestaForm(request.POST)
    if not form.is_valid():
        _mostrar_errores(request, form)
        return redirect('propuestas:aprobacion')

    try:
        form.procesar(propuesta, request.user)
        messages.success(request, MSG_02_04)
    except ReactivacionInvalidaError as e:
        messages.error(request, str(e))
    except ValidationError as e:
        messages.error(request, e.messages[0])
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
        raise PermissionDenied

    form = AccionMasivaForm(request.POST)
    if not form.is_valid():
        _mostrar_errores(request, form)
        return redirect('propuestas:aprobacion')

    try:
        procesadas = form.procesar(asignacion.carrera, request.user)
        messages.success(
            request,
            f'Se procesaron exitosamente {procesadas} propuesta(s) de forma masiva.',
        )
    except ReactivacionInvalidaError as e:
        messages.error(request, str(e))
    except ValidationError as e:
        # str() de un ValidationError devuelve la lista ['...']; se muestra solo el texto.
        messages.error(request, e.messages[0])
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
        raise PermissionDenied

    propuesta = get_object_or_404(
        Propuesta,
        pk=id_propuesta,
        proceso__estudiante_carrera__carrera=asignacion.carrera,
    )

    version = propuesta.version_plantilla
    if not (version and version.ruta_archivo):
        raise Http404('La propuesta no cuenta con documento adjunto.')

    # La ruta viene de la base de datos: solo se sirve si queda dentro de MEDIA_ROOT
    # (quien la escribe debe guardar el archivo bajo MEDIA_ROOT, es decir documentos/).
    raiz = Path(settings.MEDIA_ROOT).resolve()
    ruta = (raiz / version.ruta_archivo).resolve()
    if not (ruta.is_relative_to(raiz) and ruta.is_file()):
        raise Http404('El archivo solicitado no se encuentra en el servidor.')

    try:
        archivo = open(ruta, 'rb')
    except OSError:
        raise Http404('El archivo solicitado no se encuentra en el servidor.')
    # FileResponse cierra el archivo, deduce el tipo MIME y escapa el nombre en Content-Disposition.
    nombre = version.nombre_archivo or ruta.name
    # Solo el PDF se previsualiza inline; cualquier otro tipo (HTML, SVG, sin extensión...) se fuerza
    # como descarga para que el navegador no lo ejecute en nuestro origen (XSS almacenado).
    # Se usa mimetypes.guess_type sobre el mismo nombre con que FileResponse deduce el Content-Type.
    es_pdf = mimetypes.guess_type(nombre) == ('application/pdf', None)
    return FileResponse(archivo, filename=nombre, as_attachment=not es_pdf)
