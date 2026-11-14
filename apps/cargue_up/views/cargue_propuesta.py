"""SISTRA-03 · Cargue en la Plataforma UP: vistas y controladores web.

Implementa los flujos del requerimiento de negocio BR-03 (SISTRA-03):
- Consulta de estado del proyecto de horas sociales (CA-01, CA-02).
- Descarga segura y autenticada de la propuesta aprobada (CA-03, E2).
- Redirección y auditoría del enlace saliente a la Plataforma UP (CA-04, E3).
- Reactivación de acciones tras Rechazado en UP con observación (FA-02).
- Auditoría integral de cada acción con vocabulario estandarizado (CA-12).
"""

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from apps.cargue_up.forms.cargue_propuesta import (
    MSG_03_01,
    MSG_03_04,
    MSG_03_05,
    registrar_auditoria,
)
from apps.cargue_up.models import CargueUp, EstadoVerificacion
from apps.parametrizacion.models import Parametro
from apps.personas.models import DirectorCarrera
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import HistorialEstado


def _obtener_url_up() -> tuple[str | None, bool]:
    """Obtiene la URL oficial de la Plataforma UP desde Parametro con clave 'url_up'."""
    try:
        param = Parametro.objects.filter(clave="url_up").first()
        if param and param.valor and param.valor.strip():
            return param.valor.strip(), True
    except Exception:
        pass
    return None, False


def _obtener_documento_propuesta_pdf(propuesta: Propuesta) -> tuple[Path | None, str | None]:
    """Busca el documento PDF oficial de la propuesta aprobada.
    
    El documento oficial se genera en PDF a partir de los datos de la propuesta
    en coordinación con SISTRA-01. Mientras dicha función compartida no exista
    o el archivo no se encuentre en el servidor, retorna (None, None).
    """
    # 1. Si existe una función compartida de generación en SISTRA-01
    try:
        from apps.propuestas.servicios import generar_pdf_propuesta  # noqa
        # Si estuviera implementada en SISTRA-01, se usaría aquí
    except (ImportError, AttributeError):
        pass

    # 2. Si existe un archivo PDF asociado en MEDIA_ROOT
    if hasattr(settings, "MEDIA_ROOT") and settings.MEDIA_ROOT:
        raiz = Path(settings.MEDIA_ROOT).resolve()
        posibles_rutas = [
            raiz / "propuestas" / f"{propuesta.codigo}.pdf",
            raiz / f"{propuesta.codigo}.pdf",
        ]
        for ruta in posibles_rutas:
            if ruta.is_file():
                return ruta, f"Propuesta_{propuesta.codigo}.pdf"

    return None, None


def _obtener_propuesta_estudiante(request: HttpRequest) -> Propuesta | None:
    """Busca la propuesta activa exclusivamente del estudiante autenticado en sesión."""
    if not hasattr(request.user, "estudiante") or not request.user.estudiante:
        return None

    return (
        Propuesta.objects.filter(
            proceso__estudiante_carrera__estudiante=request.user.estudiante,
            archivada=False,
        )
        .select_related("proceso__estudiante_carrera__carrera", "version_plantilla")
        .order_by("-fecha_creacion")
        .first()
    )


@login_required
@require_GET
def inicio(request: HttpRequest) -> HttpResponse:
    """Pantalla principal de Cargue UP (BR-03 / SISTRA-03).
    
    Muestra:
    - Estado de su proyecto de horas sociales.
    - Línea de progreso (Stepper de 3 pasos).
    - Tarjeta de Paso 1 (Descarga de propuesta y enlace a la Plataforma UP).
    - Observaciones del Director si el trámite fue previamente Rechazado en UP (FA-02).
    """
    if not hasattr(request.user, "estudiante") or not request.user.estudiante:
        raise PermissionDenied

    propuesta = _obtener_propuesta_estudiante(request)
    url_up, url_up_configurada = _obtener_url_up()

    docente_nombre = "Docente asignado"
    fecha_aprobacion = None
    cargue_existente = None
    observacion_rechazo_up = None
    puede_cargar = False
    estado_actual = None
    pdf_disponible = False

    if propuesta:
        estado_actual = propuesta.estado
        pdf_ruta, _ = _obtener_documento_propuesta_pdf(propuesta)
        pdf_disponible = pdf_ruta is not None

        # Consultar el último cargue en UP registrado para este proyecto
        ultimo_cargue = (
            CargueUp.objects.filter(propuesta=propuesta)
            .order_by("-fecha_declaracion")
            .first()
        )

        if ultimo_cargue:
            if ultimo_cargue.estado_verificacion == EstadoVerificacion.RECHAZADO_EN_UP:
                # FA-02: Tras Rechazado en UP, la propuesta vuelve a Aprobado y se trata como
                # si no hubiera cargue activo, habilitando nuevamente las acciones y mostrando la observación
                cargue_existente = None
                observacion_rechazo_up = ultimo_cargue.observacion
            else:
                cargue_existente = ultimo_cargue

        # Determinar docente y fecha de aprobación desde el historial
        historial_aprobado = (
            HistorialEstado.objects.filter(
                propuesta=propuesta,
                estado_nuevo=EstadoTramite.APROBADO,
            )
            .select_related("usuario")
            .order_by("-fecha_hora")
            .first()
        )
        if historial_aprobado:
            docente_nombre = getattr(historial_aprobado.usuario, "nombre", str(historial_aprobado.usuario))
            fecha_aprobacion = historial_aprobado.fecha_hora
        else:
            try:
                carrera = propuesta.proceso.estudiante_carrera.carrera
                asig = (
                    DirectorCarrera.objects.filter(carrera=carrera, activo=True)
                    .select_related("director__usuario")
                    .first()
                )
                if asig and asig.director and asig.director.usuario:
                    docente_nombre = asig.director.usuario.nombre
            except Exception:
                pass

        # RN-01: Acciones habilitadas solo cuando el estado es Aprobado y no hay cargue pendiente
        puede_cargar = (estado_actual == EstadoTramite.APROBADO) and (cargue_existente is None)

        registrar_auditoria(
            usuario=request.user,
            accion="Acceso a pantalla de cargue en UP",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle=f"Estado del proyecto: {estado_actual}",
            resultado="Éxito",
        )
    else:
        registrar_auditoria(
            usuario=request.user,
            accion="Acceso a pantalla de cargue en UP",
            tabla_afectada="propuesta",
            detalle="Estudiante sin proyecto registrado.",
            resultado="Éxito",
        )

    contexto = {
        "propuesta": propuesta,
        "docente_nombre": docente_nombre,
        "fecha_aprobacion": fecha_aprobacion,
        "cargue_existente": cargue_existente,
        "observacion_rechazo_up": observacion_rechazo_up,
        "puede_cargar": puede_cargar,
        "estado_actual": estado_actual,
        "url_up": url_up,
        "url_up_configurada": url_up_configurada,
        "pdf_disponible": pdf_disponible,
        "EstadoTramite": EstadoTramite,
    }

    return render(request, "cargue_up/cargue_propuesta/inicio.html", contexto)


@login_required
@require_GET
def descargar_propuesta(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Descarga autenticada del documento PDF de la propuesta aprobada (CA-03, E2).
    
    - Requiere sesión y rol Estudiante (PermissionDenied a otros roles).
    - Valida que la propuesta pertenezca estrictamente al estudiante en sesión.
    - Valida que el estado permita la descarga (Aprobado o Subido en UP).
    - Mientras la función compartida de generación en PDF con SISTRA-01 no exista,
      informa al estudiante que el documento está en preparación.
    """
    if not hasattr(request.user, "estudiante") or not request.user.estudiante:
        raise PermissionDenied

    propuesta = get_object_or_404(
        Propuesta,
        pk=id_propuesta,
        proceso__estudiante_carrera__estudiante=request.user.estudiante,
    )

    # Validar que el estado permita la descarga
    if propuesta.estado not in [
        EstadoTramite.APROBADO,
        EstadoTramite.SUBIDO_EN_UP,
        EstadoTramite.APROBADO_EN_UP,
    ]:
        registrar_auditoria(
            usuario=request.user,
            accion="Descargar propuesta",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle=f"Descarga bloqueada: estado actual {propuesta.estado}",
            resultado="Bloqueado",
        )
        messages.warning(request, MSG_03_01)
        return redirect("cargue_up:cargue_propuesta")

    pdf_ruta, pdf_nombre = _obtener_documento_propuesta_pdf(propuesta)
    if not pdf_ruta or not pdf_ruta.is_file():
        registrar_auditoria(
            usuario=request.user,
            accion="Descargar propuesta",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle="Descarga no disponible: función generadora de PDF en integración con SISTRA-01.",
            resultado="Bloqueado",
        )
        messages.warning(request, MSG_03_04)
        return redirect("cargue_up:cargue_propuesta")

    registrar_auditoria(
        usuario=request.user,
        accion="Descargar propuesta",
        tabla_afectada="propuesta",
        id_registro=propuesta.pk,
        detalle=f"Descarga de propuesta {propuesta.codigo} ({pdf_nombre})",
        resultado="Éxito",
    )
    archivo = open(pdf_ruta, "rb")
    return FileResponse(archivo, filename=pdf_nombre, as_attachment=True, content_type="application/pdf")


@login_required
@require_GET
def ir_a_up(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Registra la auditoría y redirige al estudiante a la Plataforma UP (CA-04, E3).
    
    - Requiere sesión y rol Estudiante (PermissionDenied a otros roles).
    - Valida que la propuesta pertenezca estrictamente al estudiante en sesión.
    - La URL se obtiene de Parametro con clave 'url_up'. Si no está configurada,
      se bloquea la acción informando al estudiante.
    """
    if not hasattr(request.user, "estudiante") or not request.user.estudiante:
        raise PermissionDenied

    propuesta = get_object_or_404(
        Propuesta,
        pk=id_propuesta,
        proceso__estudiante_carrera__estudiante=request.user.estudiante,
    )

    url_up, configurada = _obtener_url_up()

    if not configurada or not url_up:
        registrar_auditoria(
            usuario=request.user,
            accion="Ir a la Plataforma UP",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle="Acceso bloqueado: URL de la UP no configurada en la tabla parámetro.",
            resultado="Bloqueado",
        )
        messages.error(request, MSG_03_05)
        return redirect("cargue_up:cargue_propuesta")

    registrar_auditoria(
        usuario=request.user,
        accion="Ir a la Plataforma UP",
        tabla_afectada="propuesta",
        id_registro=propuesta.pk,
        detalle=f"Redirigiendo a: {url_up}",
        resultado="Éxito",
    )
    return redirect(url_up)

