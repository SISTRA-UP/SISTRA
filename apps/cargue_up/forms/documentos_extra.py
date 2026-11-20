"""PRO-16 · Cargue de archivos restantes («Documentos extra»): reglas y servicio.

Definido con la profesora (20/11/2026): el estudiante carga hasta 4 archivos PDF,
sin etiqueta (certificado de horas, evidencias, etc.), cuando su informe queda en
«Aprobado en UP» (SISTRA-09). Puede quitar y volver a cargar hasta pulsar
«Finalizar»; ahí el proceso de Trabajo Social queda Finalizado, ya no se cambia
nada y se avisa al Director. El tamaño máximo por PDF lo define el ADMO en
SISTRA-11 (documentos_extra.max_mb, 10 MB por defecto).
"""

import os
import uuid

from django import forms
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.cargue_up.forms.verificacion_informe import director_y_carreras
from apps.cargue_up.models import DocumentoExtra
from apps.cargue_up.views.aviso_informe_servicio import informe_del_estudiante
from apps.informes.models import Informe
from apps.parametrizacion import servicios as parametros
from apps.personas.models import DirectorCarrera
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import Auditoria, Notificacion

MAXIMO_DOCUMENTOS = 4
CLAVE_MAX_MB = 'documentos_extra.max_mb'
MAX_MB_POR_DEFECTO = 10
CARPETA = 'documentos_extra'
LONGITUD_NOMBRE = 200
FIRMA_PDF = b'%PDF-'

PERMISO_ESTUDIANTE = 'cargue_up.avisar'  # el mismo del panel «Mi informe» (SISTRA-08)
TIPO_NOTIFICACION = 'Documentos extra'

ACCION_SUBIR = 'SUBIR_DOCUMENTO_EXTRA'
ACCION_QUITAR = 'QUITAR_DOCUMENTO_EXTRA'
ACCION_FINALIZAR = 'FINALIZAR_DOCUMENTOS_EXTRA'
ACCION_DESCARGAR = 'DESCARGAR_DOCUMENTO_EXTRA'
RESULTADO_EXITO = 'Éxito'
RESULTADO_BLOQUEADO = 'Bloqueado'

MSG_16_01 = 'Se cargó el documento «{nombre}».'
MSG_16_02 = 'Se quitó el documento «{nombre}».'
MSG_16_03 = 'Finalizaste tu proceso de Trabajo Social. Se avisó a tu Director.'
MSG_16_04 = 'Solo se aceptan archivos PDF.'
MSG_16_05 = 'El PDF supera el tamaño máximo de {mb} MB.'
MSG_16_06 = 'Ya cargaste el máximo de {maximo} documentos. Quita uno para cargar otro.'
MSG_16_07 = 'Carga al menos un documento antes de finalizar.'
MSG_16_08 = 'Los documentos extra no están disponibles: tu informe aún no está Aprobado en UP o ya finalizaste.'
MSG_16_09 = 'Selecciona un archivo PDF para cargar.'
MSG_16_10 = 'El archivo está vacío.'


class DocumentoExtraError(Exception):
    """Regla de negocio no cumplida; el mensaje se muestra tal cual al usuario."""


def max_mb():
    return parametros.obtener_entero(CLAVE_MAX_MB, MAX_MB_POR_DEFECTO) or MAX_MB_POR_DEFECTO


class SubirDocumentoForm(forms.Form):
    archivo = forms.FileField(
        label='Documento PDF',
        error_messages={'required': MSG_16_09, 'empty': MSG_16_10, 'invalid': MSG_16_09},
        widget=forms.ClearableFileInput(
            attrs={'class': 'form-control', 'accept': '.pdf,application/pdf'}
        ),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if not archivo.name.lower().endswith('.pdf'):
            raise forms.ValidationError(MSG_16_04)
        limite = max_mb()
        if archivo.size > limite * 1024 * 1024:
            raise forms.ValidationError(MSG_16_05.format(mb=limite))
        inicio = archivo.read(len(FIRMA_PDF))
        archivo.seek(0)
        if inicio != FIRMA_PDF:
            raise forms.ValidationError(MSG_16_04)
        return archivo


def nombre_seguro(nombre):
    """Nombre para mostrar: sin rutas y con un largo que cabe en la tabla."""
    nombre = os.path.basename(nombre.replace('\\', '/')).strip() or 'documento.pdf'
    if len(nombre) > LONGITUD_NOMBRE:
        nombre = nombre[: LONGITUD_NOMBRE - 4] + '.pdf'
    return nombre


def auditar(usuario, accion, resultado, id_registro=None, detalle=''):
    Auditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tabla_afectada='documento_extra',
        id_registro_afectado=id_registro,
        detalle=detalle,
        resultado=resultado,
    )


def estado_del_estudiante(usuario):
    """Lo que necesita el panel: informe, proceso, documentos y si se pueden cambiar."""
    informe = informe_del_estudiante(usuario)
    if informe is None or informe.estado != EstadoTramite.APROBADO_EN_UP:
        return None
    proceso = informe.propuesta.proceso
    documentos = list(informe.documentos_extra.all())
    finalizado = proceso.estado == EstadoAvance.FINALIZADA
    return {
        'informe': informe,
        'proceso': proceso,
        'documentos': documentos,
        'finalizado': finalizado,
        'puede_cargar': not finalizado and len(documentos) < MAXIMO_DOCUMENTOS,
        'maximo': MAXIMO_DOCUMENTOS,
        'max_mb': max_mb(),
    }


def _informe_editable(usuario):
    """Informe del estudiante bloqueando su proceso, o error si no se puede cambiar.

    El bloqueo del proceso serializa cargas, quitas y la finalización simultáneas
    (dos pestañas o doble clic): el cupo de 4 y el cierre no se pueden saltar.
    """
    if not usuario.has_perm(PERMISO_ESTUDIANTE):
        raise PermissionDenied
    informe = informe_del_estudiante(usuario)
    if informe is None:
        raise DocumentoExtraError(MSG_16_08)
    proceso = ProcesoTrabajoSocial.objects.select_for_update().get(pk=informe.propuesta.proceso_id)
    informe = Informe.objects.get(pk=informe.pk)
    if informe.estado != EstadoTramite.APROBADO_EN_UP or proceso.estado == EstadoAvance.FINALIZADA:
        raise DocumentoExtraError(MSG_16_08)
    return informe, proceso


def subir(usuario, archivo):
    """Guarda el PDF validado por SubirDocumentoForm. Devuelve el documento creado."""
    with transaction.atomic():
        informe, _ = _informe_editable(usuario)
        if informe.documentos_extra.count() >= MAXIMO_DOCUMENTOS:
            raise DocumentoExtraError(MSG_16_06.format(maximo=MAXIMO_DOCUMENTOS))
        ruta = default_storage.save(f'{CARPETA}/{uuid.uuid4().hex}.pdf', archivo)
        try:  # si falla el registro, el archivo guardado no debe quedar huérfano
            documento = DocumentoExtra.objects.create(
                informe=informe,
                usuario=usuario,
                nombre_archivo=nombre_seguro(archivo.name),
                ruta_archivo=ruta,
                tamano_bytes=archivo.size,
            )
            auditar(usuario, ACCION_SUBIR, RESULTADO_EXITO, documento.pk,
                    f'Informe {informe.codigo}: {documento.nombre_archivo}')
        except Exception:
            default_storage.delete(ruta)
            raise
    return documento


def quitar(usuario, id_documento):
    with transaction.atomic():
        informe, _ = _informe_editable(usuario)
        documento = informe.documentos_extra.filter(pk=id_documento).first()
        if documento is None:
            raise DocumentoExtraError(MSG_16_08)
        nombre, ruta, pk = documento.nombre_archivo, documento.ruta_archivo, documento.pk
        documento.delete()
        auditar(usuario, ACCION_QUITAR, RESULTADO_EXITO, pk, f'Informe {informe.codigo}: {nombre}')
        transaction.on_commit(lambda: default_storage.delete(ruta))
    return nombre


def _director_de(informe):
    asignacion = (
        DirectorCarrera.objects.filter(
            carrera_id=informe.propuesta.proceso.estudiante_carrera.carrera_id, activo=True
        )
        .select_related('director__usuario')
        .first()
    )
    return asignacion.director.usuario if asignacion else None


def finalizar(usuario):
    """Cierra el proceso y avisa al Director. Solo con al menos un documento."""
    with transaction.atomic():
        informe, proceso = _informe_editable(usuario)
        cantidad = informe.documentos_extra.count()
        if cantidad == 0:
            raise DocumentoExtraError(MSG_16_07)
        ahora = timezone.now()
        proceso.estado = EstadoAvance.FINALIZADA
        proceso.fecha_finalizacion = ahora
        proceso.save(update_fields=['estado', 'fecha_finalizacion'])
        director = _director_de(informe)
        if director is not None:
            estudiante = informe.propuesta.proceso.estudiante_carrera.estudiante.usuario
            Notificacion.objects.create(
                usuario=director,
                informe=informe,
                tipo=TIPO_NOTIFICACION,
                mensaje=(
                    f'{estudiante.nombre} cargó {cantidad} documento(s) extra y finalizó su '
                    f'proceso de Trabajo Social (informe {informe.codigo}).'
                ),
            )
        auditar(usuario, ACCION_FINALIZAR, RESULTADO_EXITO, informe.pk,
                f'Informe {informe.codigo}: {cantidad} documento(s); proceso finalizado.')


def documento_para_descargar(usuario, id_documento):
    """El dueño o el Director de su carrera; cualquier otro recibe 404 sin pistas."""
    documento = (
        DocumentoExtra.objects.select_related(
            'informe__propuesta__proceso__estudiante_carrera__estudiante__usuario'
        )
        .filter(pk=id_documento)
        .first()
    )
    if documento is None:
        return None
    estudiante_carrera = documento.informe.propuesta.proceso.estudiante_carrera
    if estudiante_carrera.estudiante.usuario_id == usuario.pk:
        return documento
    if usuario.has_perm('informe.aprobar'):
        try:
            _, carreras = director_y_carreras(usuario)
        except PermissionDenied:
            return None
        if estudiante_carrera.carrera_id in carreras:
            return documento
    return None


def recibidos_del_director(usuario):
    """Informes de los estudiantes del Director que ya finalizaron con documentos extra."""
    _, carreras = director_y_carreras(usuario)
    return (
        Informe.objects.filter(
            propuesta__proceso__estudiante_carrera__carrera_id__in=carreras,
            propuesta__proceso__estado=EstadoAvance.FINALIZADA,
            documentos_extra__isnull=False,
        )
        .distinct()
        .select_related('propuesta__proceso__estudiante_carrera__estudiante__usuario')
        .prefetch_related('documentos_extra')
        .order_by('-propuesta__proceso__fecha_finalizacion')
    )
