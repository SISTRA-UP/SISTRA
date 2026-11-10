"""Carga masiva de estudiantes desde un CSV.

Columnas: nombre, apellido, cc, correo, telefono (opcional) y carrera.
Cada fila se procesa en su propia transacción: una fila mala no tumba las demás.
Si se indica `carrera_permitida` (el caso de un Director), solo se aceptan
estudiantes de esa carrera.
"""
import csv
import io
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from apps.seguimiento.models import Auditoria

from .models import ROL_ESTUDIANTE, CargaMasiva, CargaMasivaFila, ResultadoFila
from .servicios import (
    ErrorCreacion, actualizar_estudiante, crear_usuario, normalizar_cedula,
    resolver_carrera, sin_tildes,
)

logger = logging.getLogger(__name__)

COLUMNAS = ('nombre', 'cc', 'correo', 'carrera', 'apellido', 'telefono')
COLUMNAS_REQUERIDAS = ('nombre', 'cc', 'correo', 'carrera')
PLANTILLA_CSV = 'nombre,cc,correo,carrera\r\n,,,\r\n,,,\r\n'


class ErrorArchivo(Exception):
    """El archivo completo no se puede procesar (formato, tamaño, columnas)."""

    def __init__(self, mensaje):
        super().__init__(mensaje)
        self.mensaje = mensaje


def _leer(archivo):
    limite = settings.CARGA_MASIVA_MAX_MB * 1024 * 1024
    contenido = archivo.read(limite + 1)
    if len(contenido) > limite:
        raise ErrorArchivo(f'El archivo supera {settings.CARGA_MASIVA_MAX_MB} MB.')
    for codificacion in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    raise ErrorArchivo('No se pudo leer el archivo. Guárdelo como CSV.')


def _parsear(texto):
    """Devuelve [(numero_de_fila, {columna: valor})] sin las filas vacías."""
    if not texto.strip():
        raise ErrorArchivo('El archivo está vacío.')
    primera = texto.splitlines()[0]
    delimitador = max(',;\t', key=primera.count)
    lector = csv.reader(io.StringIO(texto), delimiter=delimitador)
    encabezado = [sin_tildes(h) for h in next(lector)]
    faltan = [c for c in COLUMNAS_REQUERIDAS if c not in encabezado]
    if faltan:
        raise ErrorArchivo('Faltan columnas: ' + ', '.join(faltan) + '.')
    posicion = {nombre: encabezado.index(nombre) for nombre in COLUMNAS if nombre in encabezado}

    filas = []
    for numero, fila in enumerate(lector, start=2):
        if not any(celda.strip() for celda in fila):
            continue
        filas.append((numero, {
            nombre: fila[i].strip() if i < len(fila) else ''
            for nombre, i in posicion.items()
        }))
    if not filas:
        raise ErrorArchivo('El archivo no tiene filas con datos.')
    if len(filas) > settings.CARGA_MASIVA_MAX_FILAS:
        raise ErrorArchivo(
            f'El archivo tiene {len(filas)} filas; el máximo por carga es '
            f'{settings.CARGA_MASIVA_MAX_FILAS}.'
        )
    for _, datos in filas:
        datos.setdefault('apellido', '')
        datos.setdefault('telefono', '')
    return filas


def _procesar_fila(datos, numero, vistos_cc, vistos_correo, carrera_permitida=None):
    Usuario = get_user_model()
    cedula = normalizar_cedula(datos['cc'])
    correo = Usuario.objects.normalize_email(datos['correo'])
    try:
        for valor, vistos, etiqueta in ((cedula, vistos_cc, 'Cédula'), (correo, vistos_correo, 'Correo')):
            if valor and valor in vistos:
                raise ErrorCreacion(f'{etiqueta} repetido (ya aparece en la fila {vistos[valor]}).')
        if cedula:
            vistos_cc[cedula] = numero
        if correo:
            vistos_correo[correo] = numero

        carrera = resolver_carrera(datos['carrera'])
        if carrera_permitida is not None and carrera.pk != carrera_permitida.pk:
            raise ErrorCreacion(f'Solo puede registrar estudiantes de {carrera_permitida.nombre}.')

        por_cedula = Usuario.objects.select_related('rol').filter(cedula=cedula).first() if cedula else None
        por_correo = (
            Usuario.objects.select_related('rol').filter(correo_institucional__iexact=correo).first()
            if correo else None
        )
        if por_cedula and por_correo and por_cedula.pk == por_correo.pk:
            cambio = actualizar_estudiante(
                por_cedula, nombre=datos['nombre'], apellido=datos['apellido'],
                telefono=datos['telefono'], carrera=carrera,
            )
            return ResultadoFila.ACTUALIZADA, 'Datos actualizados.' if cambio else 'Sin cambios.'
        if por_cedula:
            raise ErrorCreacion('La cédula ya está registrada con otro correo.')
        if por_correo:
            raise ErrorCreacion('El correo ya está registrado con otra cédula.')

        crear_usuario(
            nombre=datos['nombre'], apellido=datos['apellido'], cedula=cedula, correo=correo,
            telefono=datos['telefono'], rol=ROL_ESTUDIANTE, carrera=carrera, auditar=False,
        )
        return ResultadoFila.CREADA, ''
    except ErrorCreacion as error:
        return ResultadoFila.ERROR, error.mensaje
    except Exception:
        logger.exception('Error inesperado en la fila %s de la carga masiva', numero)
        return ResultadoFila.ERROR, 'Error inesperado al procesar la fila.'


def procesar_csv(archivo, *, usuario, carrera_permitida=None):
    """Procesa el CSV y devuelve la `CargaMasiva` con el resultado de cada fila.
    Lanza `ErrorArchivo` si el archivo completo no es válido."""
    filas = _parsear(_leer(archivo))
    carga = CargaMasiva.objects.create(
        usuario=usuario, nombre_archivo=(archivo.name or 'carga.csv')[:200], total_filas=len(filas)
    )
    vistos_cc, vistos_correo, registros = {}, {}, []
    for numero, datos in filas:
        resultado, detalle = _procesar_fila(
            datos, numero, vistos_cc, vistos_correo, carrera_permitida
        )
        registros.append(CargaMasivaFila(
            carga=carga, numero_fila=numero, cedula=datos['cc'][:40],
            correo_institucional=datos['correo'][:254], resultado=resultado, detalle=detalle[:255],
        ))
    CargaMasivaFila.objects.bulk_create(registros)

    totales = carga.filas.aggregate(
        creadas=Count('pk', filter=Q(resultado=ResultadoFila.CREADA)),
        actualizadas=Count('pk', filter=Q(resultado=ResultadoFila.ACTUALIZADA)),
        con_error=Count('pk', filter=Q(resultado=ResultadoFila.ERROR)),
    )
    for campo, valor in totales.items():
        setattr(carga, campo, valor)
    carga.save(update_fields=list(totales))
    Auditoria.objects.create(
        usuario=usuario,
        accion='Carga masiva de estudiantes',
        tabla_afectada='carga_masiva',
        id_registro_afectado=carga.pk,
        detalle=(f'Filas: {carga.total_filas}. Creadas: {carga.creadas}. '
                 f'Actualizadas: {carga.actualizadas}. Con error: {carga.con_error}.'),
        resultado='Éxito' if carga.con_error == 0 else 'Parcial',
    )
    return carga


def _seguro(valor):
    """Evita la inyección de fórmulas al abrir el log en Excel."""
    valor = str(valor or '')
    return "'" + valor if valor[:1] in ('=', '+', '-', '@', '\t', '\r') else valor


def log_errores_csv(carga):
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(['fila', 'cc', 'correo', 'detalle'])
    for fila in carga.filas.filter(resultado=ResultadoFila.ERROR).order_by('numero_fila'):
        escritor.writerow([
            fila.numero_fila, _seguro(fila.cedula), _seguro(fila.correo_institucional),
            _seguro(fila.detalle),
        ])
    return salida.getvalue().encode('utf-8-sig')