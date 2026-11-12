"""SISTRA-03 · Cargue al sistema de UP: vistas y controladores web.

Implementa los flujos del requerimiento de negocio BR-03 (SISTRA-03):
- Consulta de estado del proyecto de horas sociales (CA-01, CA-02).
- Descarga segura y autenticada del documento del proyecto (CA-03, E2).
- Redirección y auditoría del enlace saliente a la UP (CA-04, E3).
- Notificación declarativa del cargue en la UP con modal de confirmación (CA-05, E7).
- Auditoría integral de cada acción (CA-12).
"""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cargue_up.forms.cargue_propuesta import (
    MSG_XX_06,
    MSG_XX_12,
    MSG_XX_13,
    MSG_XX_14,
    MSG_XX_15,
    MSG_XX_17,
    NotificarCargueForm,
    registrar_auditoria,
)
from apps.cargue_up.models import CargueUp
from apps.parametrizacion.models import Parametro
from apps.personas.models import DirectorCarrera
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import HistorialEstado

# URL por defecto si el administrador aún no configura el parámetro en la BD
URL_UP_FALLBACK = "https://www.unipamplona.edu.co/"


def _obtener_url_up() -> tuple[str, bool]:
    """Obtiene la URL oficial de la UP desde la tabla parametro."""
    try:
        param = Parametro.objects.filter(
            clave__in=["URL_SISTEMA_UP", "url_sistema_up", "URL_UP"]
        ).first()
        if param and param.valor and param.valor.strip():
            return param.valor.strip(), True
    except Exception:
        pass
    return URL_UP_FALLBACK, False


def _obtener_propuesta_estudiante(request: HttpRequest, id_propuesta: int | None = None) -> Propuesta | None:
    """Busca la propuesta activa del estudiante en sesión o la indicada en modo depuración/admin."""
    # 1. Caso estándar: Usuario con perfil Estudiante
    if hasattr(request.user, "estudiante"):
        qs = Propuesta.objects.filter(
            proceso__estudiante_carrera__estudiante=request.user.estudiante,
            archivada=False,
        ).select_related(
            "proceso__estudiante_carrera__carrera",
            "version_plantilla",
        )
        if id_propuesta:
            return qs.filter(pk=id_propuesta).first()
        return qs.order_by("-fecha_creacion").first()

    # 2. Soporte para desarrollo o usuarios administradores/docentes probando la vista
    if request.user.is_staff or request.user.is_superuser or settings.DEBUG:
        if id_propuesta:
            return Propuesta.objects.filter(pk=id_propuesta, archivada=False).first()
        return (
            Propuesta.objects.filter(archivada=False)
            .select_related("proceso__estudiante_carrera__carrera", "version_plantilla")
            .order_by("-fecha_creacion")
            .first()
        )

    return None


def _asegurar_sesion_estudiante(request: HttpRequest) -> None:
    """En entorno de desarrollo (DEBUG), si aún no hay sesión iniciada, auto-autentica
    al estudiante de pruebas para permitir validar la interfaz directamente sin depender de otros módulos."""
    if not request.user.is_authenticated and settings.DEBUG:
        from apps.personas.models import Estudiante
        from django.contrib.auth import login

        est = Estudiante.objects.select_related("usuario").first()
        if est and est.usuario:
            login(request, est.usuario)


@require_GET
def inicio(request: HttpRequest) -> HttpResponse:
    """Pantalla principal de Cargue UP (BR-03 / SISTRA-03).
    
    Muestra:
    - Estado de su proyecto de horas sociales.
    - Línea de progreso (Stepper de 3 pasos).
    - Tarjeta de Paso 1 (Descarga + Link a la UP).
    - Tarjeta de Paso 2 (Ya cargué mi proyecto).
    - Modal de confirmación.
    """
    _asegurar_sesion_estudiante(request)
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    id_solicitado = request.GET.get("propuesta_id")
    id_num = int(id_solicitado) if id_solicitado and id_solicitado.isdigit() else None

    propuesta = _obtener_propuesta_estudiante(request, id_propuesta=id_num)

    url_up, url_up_configurada = _obtener_url_up()

    docente_nombre = "Docente asignado"
    fecha_aprobacion = None
    cargue_existente = None
    puede_cargar = False
    estado_actual = None

    if propuesta:
        estado_actual = propuesta.estado
        cargue_existente = CargueUp.objects.filter(propuesta=propuesta).order_by("-fecha_declaracion").first()

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
            # Si no hay historial aún, consultar el Director activo de la carrera
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

        # RN-01: Las acciones se habilitan solo cuando el estado es Aprobado
        # y no existe una notificación de cargue ya registrada (A3 / CA-01)
        puede_cargar = (estado_actual == EstadoTramite.APROBADO) and (cargue_existente is None)

        # Auditoría de acceso a la pantalla
        registrar_auditoria(
            usuario=request.user,
            accion="ACCESO_CARGUE_UP",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle=f"Estado del proyecto: {estado_actual}",
            resultado="EXITO",
        )
    else:
        registrar_auditoria(
            usuario=request.user,
            accion="ACCESO_CARGUE_UP_SIN_PROYECTO",
            tabla_afectada="propuesta",
            detalle="Estudiante sin proyecto registrado.",
            resultado="INFO",
        )

    formulario = NotificarCargueForm(
        propuesta=propuesta,
        initial={"fecha_cargue": timezone.localdate()},
    )

    contexto = {
        "propuesta": propuesta,
        "docente_nombre": docente_nombre,
        "fecha_aprobacion": fecha_aprobacion,
        "cargue_existente": cargue_existente,
        "puede_cargar": puede_cargar,
        "estado_actual": estado_actual,
        "url_up": url_up,
        "url_up_configurada": url_up_configurada,
        "formulario": formulario,
        "EstadoTramite": EstadoTramite,
    }

    return render(request, "cargue_up/cargue_propuesta/inicio.html", contexto)


@require_GET
def descargar_propuesta(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Descarga autenticada del documento de la propuesta (CA-03, E2).
    
    - Valida que el estudiante sea el dueño del proyecto (CA-08, RN-04).
    - Valida que el estado permita la descarga (Aprobado o Subido en UP).
    - No expone rutas internas del servidor.
    """
    _asegurar_sesion_estudiante(request)
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    propuesta = get_object_or_404(Propuesta, pk=id_propuesta)

    # Validar autorización por propiedad (CA-08)
    if hasattr(request.user, "estudiante"):
        estudiante_propuesta = getattr(propuesta.proceso.estudiante_carrera, "estudiante", None)
        if estudiante_propuesta != request.user.estudiante:
            registrar_auditoria(
                usuario=request.user,
                accion="DESCARGA_DENEGADA_NO_PROPIETARIO",
                tabla_afectada="propuesta",
                id_registro=propuesta.pk,
                detalle="Intento de descarga de un proyecto de otro estudiante.",
                resultado="DENEGADO",
            )
            messages.error(request, MSG_XX_17)
            return redirect("cargue_up:cargue_propuesta")

    # Validar estado para descarga
    if propuesta.estado not in [EstadoTramite.APROBADO, EstadoTramite.SUBIDO_EN_UP, EstadoTramite.APROBADO_EN_UP]:
        messages.warning(
            request,
            "El documento solo está disponible para descarga cuando la propuesta ha sido aprobada.",
        )
        return redirect("cargue_up:cargue_propuesta")

    # Intentar resolver el archivo adjunto
    version = propuesta.version_plantilla
    if not (version and version.ruta_archivo):
        registrar_auditoria(
            usuario=request.user,
            accion="DESCARGA_FALLIDA_SIN_ARCHIVO",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle="La propuesta no tiene ruta de archivo asociada en version_plantilla.",
            resultado="ERROR",
        )
        messages.error(request, MSG_XX_12)
        return redirect("cargue_up:cargue_propuesta")

    raiz = Path(settings.MEDIA_ROOT).resolve()
    ruta = (raiz / version.ruta_archivo).resolve()

    if not (ruta.is_relative_to(raiz) and ruta.is_file()):
        registrar_auditoria(
            usuario=request.user,
            accion="DESCARGA_FALLIDA_ARCHIVO_INEXISTENTE",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle=f"Archivo no encontrado en disco: {version.ruta_archivo}",
            resultado="ERROR",
        )
        messages.error(request, MSG_XX_12)
        return redirect("cargue_up:cargue_propuesta")

    try:
        archivo = open(ruta, "rb")
    except OSError:
        registrar_auditoria(
            usuario=request.user,
            accion="DESCARGA_FALLIDA_ERROR_LECTURA",
            tabla_afectada="propuesta",
            id_registro=propuesta.pk,
            detalle="Error de lectura del archivo en el sistema operativo.",
            resultado="ERROR",
        )
        messages.error(request, MSG_XX_12)
        return redirect("cargue_up:cargue_propuesta")

    registrar_auditoria(
        usuario=request.user,
        accion="DESCARGA_PROYECTO_EXITOSA",
        tabla_afectada="propuesta",
        id_registro=propuesta.pk,
        detalle=f"Archivo: {version.nombre_archivo or ruta.name}",
        resultado="EXITO",
    )

    nombre = version.nombre_archivo or f"Propuesta_{propuesta.codigo}.pdf"
    es_pdf = mimetypes.guess_type(nombre)[0] == "application/pdf"
    return FileResponse(archivo, filename=nombre, as_attachment=not es_pdf)


@require_POST
def notificar_cargue(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Procesa el formulario modal de 'Ya cargué mi proyecto' (CA-05, RN-04)."""
    _asegurar_sesion_estudiante(request)
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    propuesta = get_object_or_404(Propuesta, pk=id_propuesta)

    # Validar propiedad (CA-08)
    if hasattr(request.user, "estudiante"):
        estudiante_propuesta = getattr(propuesta.proceso.estudiante_carrera, "estudiante", None)
        if estudiante_propuesta != request.user.estudiante:
            registrar_auditoria(
                usuario=request.user,
                accion="NOTIFICAR_CARGUE_DENEGADO_NO_PROPIETARIO",
                tabla_afectada="propuesta",
                id_registro=propuesta.pk,
                detalle="Intento de notificar cargue de proyecto ajeno.",
                resultado="DENEGADO",
            )
            messages.error(request, MSG_XX_17)
            return redirect("cargue_up:cargue_propuesta")

    # Validar que siga en Aprobado (E4)
    if propuesta.estado != EstadoTramite.APROBADO:
        messages.warning(request, MSG_XX_14)
        return redirect("cargue_up:cargue_propuesta")

    formulario = NotificarCargueForm(request.POST, propuesta=propuesta)
    if formulario.is_valid():
        try:
            formulario.procesar(propuesta, request.user)
            messages.success(request, MSG_XX_06)
        except ValidationError as e:
            messages.warning(request, e.messages[0] if hasattr(e, "messages") else str(e))
        except Exception:
            registrar_auditoria(
                usuario=request.user,
                accion="NOTIFICAR_CARGUE_ERROR_SISTEMA",
                tabla_afectada="propuesta",
                id_registro=propuesta.pk,
                detalle="Fallo inesperado al procesar la notificación de cargue.",
                resultado="ERROR",
            )
            messages.error(request, MSG_XX_13)
    else:
        # Extraer primer error de validación para mensaje visible
        for campo, errores in formulario.errors.items():
            for error in errores:
                messages.error(request, error)
                break
            break

    return redirect("cargue_up:cargue_propuesta")


def ir_a_up(request: HttpRequest, id_propuesta: int) -> HttpResponse:
    """Registra la auditoría del clic en 'Ir al sistema de la UP' y redirige a la URL configurada (CA-04, E3)."""
    _asegurar_sesion_estudiante(request)
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")

    propuesta = get_object_or_404(Propuesta, pk=id_propuesta)

    url_up, configurada = _obtener_url_up()

    registrar_auditoria(
        usuario=request.user,
        accion="CLIC_IR_SISTEMA_UP",
        tabla_afectada="propuesta",
        id_registro=propuesta.pk,
        detalle=f"Redirigiendo a URL externa: {url_up} (Configurada en BD: {configurada})",
        resultado="EXITO",
    )

    if not configurada and not url_up:
        messages.error(request, MSG_XX_15)
        return redirect("cargue_up:cargue_propuesta")

    # Si es una petición AJAX (fetch), responder JSON
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "url": url_up})

    # Redirección directa si se abre por enlace
    return redirect(url_up)
