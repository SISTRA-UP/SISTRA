"""SISTRA-07 · Aprobación de informe: vistas.

Solo el responsable de este requisito edita este archivo.
"""

import logging

from apps.usuarios.permisos import requiere_permiso
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET

from apps.cargue_up.models import CargueUp
from apps.informes.forms.aprobacion import DecisionInformeForm
from apps.informes.models import Informe
from apps.informes.views.aprobacion_semaforo import (
    calcular_semaforo_informe,
)
from apps.informes.views.aprobacion_auditoria import auditar_intentos
from apps.personas.models import DirectorCarrera
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, obtener_limites_semaforo
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import Auditoria


logger = logging.getLogger(__name__)


def generar_pdf_informe(informe):
    """Punto de conexión con B1b; ajustar esta importación al publicar su servicio."""
    from apps.propuestas.services.documentos_pdf import generar_pdf_informe as generar

    return generar(informe)


def _informes_del_director(usuario):
    """Limita los informes a las carreras del Director autorizado."""

    if (
        not usuario.is_authenticated
        or not usuario.is_active
        or usuario.es_administrador
        or not usuario.has_perm("informe.aprobar")
    ):
        raise PermissionDenied(
            "No tienes autorización para evaluar informes."
        )

    carreras = DirectorCarrera.objects.filter(
        director__usuario=usuario,
        activo=True,
    ).values_list("carrera_id", flat=True)

    if not carreras.exists():
        raise PermissionDenied(
            "No tienes una carrera asignada como Director activo."
        )

    return (
        Informe.objects.filter(
            propuesta__proceso__estudiante_carrera__carrera_id__in=carreras,
            archivado=False,
        )
        .exclude(estado=EstadoTramite.BORRADOR)
        .select_related(
            "propuesta",
            "propuesta__proceso__estudiante_carrera__estudiante__usuario",
            "propuesta__proceso__estudiante_carrera__carrera",
            "periodo_academico",
        )
    )


@requiere_permiso("informe.aprobar")
@require_GET
def bandeja(request):
    """Presenta informes con filtros y tiempo acumulado de revisión."""

    informes = _informes_del_director(request.user)

    buscar = request.GET.get("buscar", "").strip()
    estado = request.GET.get("estado", "").strip()
    color = request.GET.get("semaforo", "").strip()

    estados = [
        (valor, etiqueta)
        for valor, etiqueta in EstadoTramite.choices
        if valor != EstadoTramite.BORRADOR
    ]

    if estado not in dict(estados):
        estado = ""

    colores = [
        ("verde", "Verde"),
        ("amarillo", "Amarillo"),
        ("rojo", "Rojo"),
    ]

    if color not in dict(colores):
        color = ""

    if buscar:
        informes = informes.filter(
            Q(codigo__icontains=buscar)
            | Q(propuesta__titulo__icontains=buscar)
            | Q(propuesta__proceso__estudiante_carrera__estudiante__usuario__nombre__icontains=buscar)
            | Q(propuesta__proceso__estudiante_carrera__estudiante__usuario__cedula__icontains=buscar)
        )

    if estado:
        informes = informes.filter(estado=estado)

    if color:
        informes = informes.filter(
            estado=EstadoTramite.EN_REVISION,
        )

    limites = obtener_limites_semaforo()
    verde, amarillo = limites

    if not 0 <= verde < amarillo:
        limites = (7, 14)
        verde, amarillo = limites

    ahora = timezone.now()

    informes = (
        informes.annotate(
            tiene_cargue_up=Exists(
                CargueUp.objects.filter(informe_id=OuterRef("pk"))
            )
        )
        .prefetch_related("historial")
        .order_by("-fecha_envio", "-pk")
    )

    def preparar(informe):
        informe.version_decision = (
            informe.fecha_actualizacion.isoformat()
        )

        informe.puede_decidir = (
            informe.estado == EstadoTramite.EN_REVISION
            or (
                informe.estado == EstadoTramite.APROBADO
                and not informe.tiene_cargue_up
            )
        )

        informe.semaforo = calcular_semaforo_informe(
            informe,
            limites=limites,
            ahora=ahora,
        )

        return informe

    if color:
        # El filtro usa exactamente el mismo cálculo que la etiqueta.
        # Se calcula antes de paginar para obtener el total correcto.
        coincidencias = []

        for informe in informes:
            preparar(informe)

            if informe.semaforo["color"] == color:
                coincidencias.append(informe)

        pagina = Paginator(coincidencias, 10).get_page(
            request.GET.get("page")
        )
    else:
        pagina = Paginator(informes, 10).get_page(
            request.GET.get("page")
        )

        pagina.object_list = [
            preparar(informe)
            for informe in pagina.object_list
        ]

    filtros = request.GET.copy()
    filtros.pop("page", None)

    return render(
        request,
        "informes/aprobacion/bandeja.html",
        {
            "pagina": pagina,
            "buscar": buscar,
            "estado_seleccionado": estado,
            "color_seleccionado": color,
            "estados": estados,
            "colores": colores,
            "hay_filtros": bool(buscar or estado or color),
            "filtros_url": filtros.urlencode(),
            "limite_verde": verde,
            "inicio_amarillo": verde + 1,
            "limite_amarillo": amarillo,
            "inicio_rojo": amarillo + 1,
            "form_decision": DecisionInformeForm(),
        },
    )


@auditar_intentos('documento_informe')
@requiere_permiso('informe.aprobar')
@require_GET
def documento(request, id_informe):
    """Previsualiza o descarga el PDF al vuelo para el Director de la carrera."""
    informe = get_object_or_404(_informes_del_director(request.user), pk=id_informe)

    try:
        pdf = generar_pdf_informe(informe)
        if hasattr(pdf, 'read'):
            pdf = pdf.read()
        if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF-'):
            raise ValueError('El generador no devolvió un PDF válido.')
    except Exception:
        logger.exception('No se pudo generar el documento del informe %s.', informe.pk)
        return HttpResponse('El documento del informe no está disponible.', status=503)

    descargar = request.GET.get('descargar') == '1'
    respuesta = HttpResponse(pdf, content_type='application/pdf')
    respuesta['Content-Disposition'] = content_disposition_header(
        as_attachment=descargar, filename=f'informe_{informe.codigo}.pdf',
    )
    Auditoria.objects.create(
        usuario=request.user, accion='documento_informe',
        tabla_afectada='informe', id_registro_afectado=informe.pk,
        resultado=RESULTADO_EXITO,
        detalle=f"{'Descarga' if descargar else 'Consulta'} del PDF del informe {informe.codigo}.",
    )
    return respuesta
