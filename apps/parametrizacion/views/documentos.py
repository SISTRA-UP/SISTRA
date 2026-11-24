"""SISTRA-11 / SISTRA-01 · Parametrización: vistas de documentos y formatos."""

import os

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.views import View

from apps.parametrizacion.models import Plantilla, VersionPlantilla


class DescargaPlantillaPropuestaEstudianteView(LoginRequiredMixin, View):
    """Descarga la versión vigente de la plantilla de propuesta para el Estudiante.

    Accesible a cualquier usuario autenticado (SISTRA-01 necesita que el
    estudiante baje el Word antes de iniciar su propuesta).
    Si hay versión vigente en BD y el archivo existe en MEDIA_ROOT, la sirve.
    Si aún no hay versión registrada en BD pero existe la plantilla oficial base
    en MEDIA_ROOT o en el proyecto, la sirve como fallback institucional.
    URL: parametrizacion:plantilla_propuesta_estudiante
    """

    def get(self, request):
        # 1. Buscar en BD versión vigente de plantilla de propuesta
        try:
            plantilla = Plantilla.objects.filter(tipo='propuesta', estado='Activo').first()
            if plantilla:
                version = plantilla.versiones.filter(es_vigente=True).first()
                if version:
                    ruta = os.path.join(settings.MEDIA_ROOT, version.ruta_archivo)
                    if os.path.exists(ruta):
                        return FileResponse(
                            open(ruta, 'rb'),
                            as_attachment=True,
                            filename=version.nombre_archivo,
                        )
        except Exception:
            pass

        # 2. Fallback al archivo de plantilla oficial en disco
        posibles_rutas = [
            os.path.join(settings.MEDIA_ROOT, 'documentos', 'plantilla_propuesta_trabajo_social.docx'),
            os.path.join(settings.MEDIA_ROOT, 'plantilla_propuesta_trabajo_social.docx'),
            os.path.join(settings.BASE_DIR, 'documentos', 'plantilla_propuesta_trabajo_social.docx'),
            os.path.join(settings.BASE_DIR, 'static', 'plantillas', 'plantilla_propuesta_trabajo_social.docx'),
        ]
        for ruta in posibles_rutas:
            if os.path.exists(ruta):
                return FileResponse(
                    open(ruta, 'rb'),
                    as_attachment=True,
                    filename='plantilla_propuesta_trabajo_social.docx',
                )

        raise Http404('No hay versión vigente de la plantilla de propuesta.')
