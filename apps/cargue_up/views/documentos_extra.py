"""PRO-16 · Cargue de archivos restantes («Documentos extra»): vistas.

El estudiante carga, quita y finaliza desde su panel en la pantalla «Cargue UP»
(todo el trámite en una sola pantalla). El Director consulta y descarga en
«Documentos extra recibidos». Las reglas viven en forms/documentos_extra.py.
"""

from django.contrib import messages
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.forms import documentos_extra as servicio
from apps.usuarios.permisos import requiere_permiso

POR_PAGINA = 20


def _volver_al_panel():
    # Sin ancla: el mensaje del resultado se muestra arriba de la pantalla, como en SISTRA-08.
    return redirect('cargue_up:cargue_propuesta')


@never_cache
@requiere_permiso(servicio.PERMISO_ESTUDIANTE)
@require_POST
def subir(request):
    formulario = servicio.SubirDocumentoForm(request.POST, request.FILES)
    if not formulario.is_valid():
        for error in formulario.errors.get('archivo', [servicio.MSG_16_09]):
            messages.error(request, error)
        return _volver_al_panel()
    try:
        documento = servicio.subir(request.user, formulario.cleaned_data['archivo'])
    except servicio.DocumentoExtraError as error:
        servicio.auditar(request.user, servicio.ACCION_SUBIR, servicio.RESULTADO_BLOQUEADO,
                         detalle=str(error))
        messages.warning(request, str(error))
    else:
        messages.success(request, servicio.MSG_16_01.format(nombre=documento.nombre_archivo))
    return _volver_al_panel()


@never_cache
@requiere_permiso(servicio.PERMISO_ESTUDIANTE)
@require_POST
def quitar(request, id_documento):
    try:
        nombre = servicio.quitar(request.user, id_documento)
    except servicio.DocumentoExtraError as error:
        servicio.auditar(request.user, servicio.ACCION_QUITAR, servicio.RESULTADO_BLOQUEADO,
                         id_documento, str(error))
        messages.warning(request, str(error))
    else:
        messages.success(request, servicio.MSG_16_02.format(nombre=nombre))
    return _volver_al_panel()


@never_cache
@requiere_permiso(servicio.PERMISO_ESTUDIANTE)
@require_POST
def finalizar(request):
    try:
        servicio.finalizar(request.user)
    except servicio.DocumentoExtraError as error:
        servicio.auditar(request.user, servicio.ACCION_FINALIZAR, servicio.RESULTADO_BLOQUEADO,
                         detalle=str(error))
        messages.warning(request, str(error))
    else:
        messages.success(request, servicio.MSG_16_03)
    return _volver_al_panel()


@never_cache
@require_GET
def descargar(request, id_documento):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('usuarios:login')}?next={request.path}")
    documento = servicio.documento_para_descargar(request.user, id_documento)
    if documento is None or not default_storage.exists(documento.ruta_archivo):
        servicio.auditar(request.user, servicio.ACCION_DESCARGAR, servicio.RESULTADO_BLOQUEADO,
                         id_documento, 'Documento inexistente o sin permiso.')
        raise Http404
    return FileResponse(
        default_storage.open(documento.ruta_archivo, 'rb'),
        as_attachment=True,
        filename=documento.nombre_archivo,
        content_type='application/pdf',
    )


@never_cache
@requiere_permiso('informe.aprobar')
@require_GET
def recibidos(request):
    informes = servicio.recibidos_del_director(request.user)
    pagina = Paginator(informes, POR_PAGINA).get_page(request.GET.get('pagina'))
    return render(request, 'cargue_up/documentos_extra/recibidos.html', {
        'pagina': pagina,
        'filas': [
            {
                'informe': informe,
                'estudiante': informe.propuesta.proceso.estudiante_carrera.estudiante.usuario,
                'fecha_finalizacion': informe.propuesta.proceso.fecha_finalizacion,
                'documentos': list(informe.documentos_extra.all()),
            }
            for informe in pagina
        ],
    })
