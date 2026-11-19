
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.forms.verificacion_propuesta import (
    DecisionPropuestaForm,
    CorreccionPropuestaForm,
)
from apps.cargue_up.models import (
    CargueUp,
    EstadoVerificacion,
    HistorialCargueUp,
)
from apps.personas.models import Director, DirectorCarrera
from apps.propuestas.models import Propuesta, EstadoTramite


def _director_y_carreras(usuario):
    if not usuario.is_authenticated or not usuario.has_perm('informe.aprobar'):
        raise PermissionDenied

    director = get_object_or_404(Director, usuario=usuario)

    carreras = DirectorCarrera.objects.filter(
        director=director,
        activo=True,
    ).values_list('carrera_id', flat=True)

    return director, carreras


def _propuestas_del_director(usuario):
    director, carreras = _director_y_carreras(usuario)

    return (
        Propuesta.objects.filter(
            proceso__estudiante_carrera__carrera_id__in=carreras,
            archivada=False,
        )
        .select_related(
            'proceso',
            'proceso__estudiante_carrera',
            'proceso__estudiante_carrera__estudiante',
        )
        .prefetch_related('cargues_up')
        .distinct()
    )


def _ultimo_cargue(propuesta, bloquear=False):
    cargues = CargueUp.objects.filter(propuesta=propuesta)

    if bloquear:
        cargues = cargues.select_for_update()

    return cargues.order_by('-fecha_declaracion', '-id_cargue_up').first()


@login_required
@require_GET
def lista(request):
    propuestas = _propuestas_del_director(request.user).filter(
        estado=EstadoTramite.SUBIDO_EN_UP,
    )

    pendientes = []

    for propuesta in propuestas:
        cargue = _ultimo_cargue(propuesta)

        if cargue and cargue.estado_verificacion == EstadoVerificacion.PENDIENTE:
            pendientes.append({
                'propuesta': propuesta,
                'cargue': cargue,
            })

    return render(
        request,
        'cargue_up/verificacion_propuesta/lista.html',
        {'pendientes': pendientes},
    )


@login_required
@require_GET
def detalle(request, id_propuesta):
    propuesta = get_object_or_404(
        _propuestas_del_director(request.user),
        id_propuesta=id_propuesta,
    )

    cargue = _ultimo_cargue(propuesta)

    return render(
        request,
        'cargue_up/verificacion_propuesta/detalle.html',
        {
            'propuesta': propuesta,
            'cargue': cargue,
            'decision_form': DecisionPropuestaForm(),
            'correccion_form': CorreccionPropuestaForm(),
            'historial': (
                cargue.historial.select_related('director').order_by('-fecha_hora')
                if cargue else []
            ),
        },
    )


@login_required
@require_POST
def decidir(request, id_propuesta):
    director, _ = _director_y_carreras(request.user)
    form = DecisionPropuestaForm(request.POST)

    if not form.is_valid():
        messages.error(request, 'Revisa los datos de la verificación.')
        return redirect(
            'cargue_up:verificacion_propuesta_detalle',
            id_propuesta=id_propuesta,
        )

    with transaction.atomic():
        propuesta = get_object_or_404(
            _propuestas_del_director(request.user).select_for_update(),
            id_propuesta=id_propuesta,
        )
        cargue = _ultimo_cargue(propuesta, bloquear=True)

        if (
            propuesta.estado != EstadoTramite.SUBIDO_EN_UP
            or cargue is None
            or cargue.estado_verificacion != EstadoVerificacion.PENDIENTE
        ):
            messages.error(
                request,
                'Esta propuesta ya no tiene un cargue pendiente de verificación.',
            )
            return redirect('cargue_up:verificacion_propuesta_lista')

        resultado = form.cleaned_data['resultado']
        observacion = form.cleaned_data['observacion']

        cargue.director = director
        cargue.estado_verificacion = resultado
        cargue.fecha_verificacion = timezone.now()
        cargue.observacion = observacion
        cargue.save(update_fields=[
            'director',
            'estado_verificacion',
            'fecha_verificacion',
            'observacion',
        ])

        if resultado == EstadoVerificacion.APROBADO_EN_UP:
            propuesta.estado = EstadoTramite.APROBADO_EN_UP
            mensaje = 'La propuesta fue aprobada en UP.'
        else:
            propuesta.estado = EstadoTramite.APROBADO
            mensaje = 'La propuesta fue rechazada en UP.'

        propuesta.save(update_fields=['estado', 'fecha_actualizacion'])

    messages.success(request, mensaje)
    return redirect('cargue_up:verificacion_propuesta_lista')


@login_required
@require_POST
def corregir(request, id_propuesta):
    director, _ = _director_y_carreras(request.user)
    form = CorreccionPropuestaForm(request.POST)

    if not form.is_valid():
        messages.error(request, 'Revisa los datos de la corrección.')
        return redirect(
            'cargue_up:verificacion_propuesta_detalle',
            id_propuesta=id_propuesta,
        )

    with transaction.atomic():
        propuesta = get_object_or_404(
            _propuestas_del_director(request.user).select_for_update(),
            id_propuesta=id_propuesta,
        )
        cargue = _ultimo_cargue(propuesta, bloquear=True)

        if cargue is None or cargue.estado_verificacion == EstadoVerificacion.PENDIENTE:
            messages.error(
                request,
                'No existe una verificación que pueda corregirse.',
            )
            return redirect(
                'cargue_up:verificacion_propuesta_detalle',
                id_propuesta=id_propuesta,
            )

        resultado_anterior = cargue.estado_verificacion
        resultado_nuevo = form.cleaned_data['resultado']

        if resultado_anterior == resultado_nuevo:
            messages.error(request, 'Selecciona un resultado diferente al actual.')
            return redirect(
                'cargue_up:verificacion_propuesta_detalle',
                id_propuesta=id_propuesta,
            )

        HistorialCargueUp.objects.create(
            cargue_up=cargue,
            director=director,
            estado_anterior=resultado_anterior,
            estado_nuevo=resultado_nuevo,
            observacion=form.cleaned_data['observacion'],
            motivo_correccion=form.cleaned_data['motivo'],
        )

        cargue.director = director
        cargue.estado_verificacion = resultado_nuevo
        cargue.fecha_verificacion = timezone.now()
        cargue.observacion = form.cleaned_data['observacion']
        cargue.save(update_fields=[
            'director',
            'estado_verificacion',
            'fecha_verificacion',
            'observacion',
        ])

        if resultado_nuevo == EstadoVerificacion.APROBADO_EN_UP:
            propuesta.estado = EstadoTramite.APROBADO_EN_UP
        else:
            propuesta.estado = EstadoTramite.APROBADO

        propuesta.save(update_fields=['estado', 'fecha_actualizacion'])

    messages.success(request, 'La verificación fue corregida correctamente.')
    return redirect(
        'cargue_up:verificacion_propuesta_detalle',
        id_propuesta=id_propuesta,
    )
