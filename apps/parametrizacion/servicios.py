"""SISTRA-11 · Lectura y escritura de parámetros (tabla `parametro`).

Los valores iniciales viven aquí y se usan mientras el Administrador no guarde
uno propio; así no hace falta sembrar filas (la tabla exige un usuario).
Los demás módulos leen con `obtener`, `obtener_entero` y `color_semaforo`.
"""
from django.db import transaction

from apps.seguimiento.models import Auditoria

from .models import Parametro

# clave: (valor inicial, o None si el equipo aún no lo definió, descripción)
PARAMETROS_POR_DEFECTO = {
    'semaforo.verde_hasta_dias': ('7', 'Días en revisión hasta los que el semáforo está en verde.'),
    'semaforo.amarillo_hasta_dias': ('14', 'Días en revisión hasta los que el semáforo está en amarillo; después es rojo.'),
    'recordatorio.frecuencia_dias': ('7', 'Cada cuántos días se recuerda al estudiante declarar «Subido en UP».'),
    'registro_estudiantes.maximo_filas_csv': ('100', 'Máximo de filas por carga masiva de estudiantes.'),
    'registro_estudiantes.max_mb_csv': ('2', 'Tamaño máximo (MB) del CSV de carga masiva.'),
    'propuesta.max_mb_docx': ('10', 'Tamaño máximo (MB) del archivo Word de propuesta.'),
    'url_up': (None, 'Dirección de la plataforma UP.'),
    'dias_archivado_propuesta_rechazada': (None, 'Días para archivar una propuesta rechazada.'),
    'dias_archivado_informe_rechazado': (None, 'Días para archivar un informe rechazado.'),
}


def obtener(clave):
    """Valor guardado o, si no hay, el inicial (puede ser None)."""
    if clave not in PARAMETROS_POR_DEFECTO:
        raise KeyError(clave)
    guardado = Parametro.objects.filter(clave=clave).values_list('valor', flat=True).first()
    return guardado if guardado is not None else PARAMETROS_POR_DEFECTO[clave][0]


def obtener_entero(clave, default=None):
    try:
        return int(obtener(clave))
    except (TypeError, ValueError):
        return default


def guardar(clave, valor, usuario):
    """Guarda un parámetro y registra el cambio en auditoría.
    Devuelve True si algo cambió; si el valor ya es el vigente (o el inicial),
    no escribe nada."""
    if clave not in PARAMETROS_POR_DEFECTO:
        raise KeyError(clave)
    valor = '' if valor is None else str(valor).strip()
    with transaction.atomic():
        parametro = Parametro.objects.select_for_update().filter(clave=clave).first()
        inicial = PARAMETROS_POR_DEFECTO[clave][0]
        anterior = parametro.valor if parametro else inicial
        if valor == (anterior or ''):
            return False
        if parametro is None:
            parametro = Parametro.objects.create(
                clave=clave, valor=valor, descripcion=PARAMETROS_POR_DEFECTO[clave][1],
                usuario_actualizacion=usuario,
            )
        else:
            parametro.valor = valor
            parametro.usuario_actualizacion = usuario
            parametro.save(update_fields=['valor', 'usuario_actualizacion', 'fecha_actualizacion'])
        Auditoria.objects.create(
            usuario=usuario, accion='Modificar parámetro', tabla_afectada='parametro',
            id_registro_afectado=parametro.pk, detalle=f'{clave}: {anterior!r} → {valor!r}',
            resultado='Éxito',
        )
    return True


def color_semaforo(dias_en_revision):
    """'verde', 'amarillo' o 'rojo' según los días calendario en revisión."""
    dias = max(int(dias_en_revision), 0)
    if dias <= obtener_entero('semaforo.verde_hasta_dias'):
        return 'verde'
    if dias <= obtener_entero('semaforo.amarillo_hasta_dias'):
        return 'amarillo'
    return 'rojo'