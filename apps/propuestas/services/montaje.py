"""SISTRA-01 · Montaje de propuesta: servicio de extracción de plantilla Word.

Solo el lector XML (zipfile) se usa; python-docx no está en pyproject.toml.
"""
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

from apps.propuestas.models import SectorEntidad


class PlantillaInvalidaError(Exception):
    """El archivo no es la plantilla de SISTRA o su estructura fue modificada."""


# ---------------------------------------------------------------------------
# Etiquetas exactas del BRD SISTRA-01 (tabla de campos)
# Una sola etiqueta por campo — coincidencia estricta con la plantilla oficial.
# ---------------------------------------------------------------------------
ETIQUETAS_CAMPOS: dict[str, str] = {
    'Título de la propuesta': 'titulo',
    'Entidad': 'entidad',
    'Sector de la entidad': 'sector_entidad',
    'Población beneficiada': 'poblacion_beneficiada',
    'Identificación de la población': 'identificacion_poblacion',
    'Reseña histórica': 'resena_historica',
    'Identificación de la necesidad': 'identificacion_necesidad',
    'Justificación': 'justificacion',
    'Objetivos': 'objetivos',
    'Referente teórico': 'referente_teorico',
    'Propuesta social': 'propuesta_social',
    'Impacto social': 'impacto_social',
    'Zona': 'zona',
    'Área': 'area',
    'Sector': 'sector',
    'Unidad': 'unidad',
}

# Todos los campos que deben estar presentes para que la plantilla sea válida
CAMPOS_PLANTILLA_REQUERIDOS: frozenset[str] = frozenset(ETIQUETAS_CAMPOS.values())

# Lookup normalizado: texto normalizado -> campo del modelo
def _norm(t: str) -> str:
    return unicodedata.normalize('NFKD', t).encode('ASCII', 'ignore').decode().lower().strip()

_LOOKUP: dict[str, str] = {
    _norm(etiqueta): campo
    for etiqueta, campo in ETIQUETAS_CAMPOS.items()
}

# Valores válidos para sector_entidad (SectorEntidad choices)
_SECTORES_VALIDOS: set[str] = {
    unicodedata.normalize('NFKD', v).encode('ASCII', 'ignore').decode().lower().strip()
    for v in [SectorEntidad.PUBLICO, SectorEntidad.PRIVADO]
}


def normalizar_etiqueta(texto: str) -> str:
    """Normaliza texto removiendo tildes, mayúsculas y caracteres de puntuación."""
    t = unicodedata.normalize('NFKD', texto or '').encode('ASCII', 'ignore').decode().lower()
    return re.sub(r'[\s:._\-]+', ' ', t).strip()


def extraer_datos_plantilla(archivo) -> tuple[dict[str, str], list[str]]:
    """Extrae pares campo -> texto desde un .docx de la plantilla oficial SISTRA.

    Returns:
        (datos, avisos): datos extraídos y lista de advertencias (p.ej. sector inválido).

    Raises:
        PlantillaInvalidaError: si el archivo no es la plantilla oficial o faltan etiquetas.
    """
    if hasattr(archivo, 'read'):
        contenido = archivo.read()
        archivo_bytes = BytesIO(contenido)
    else:
        archivo_bytes = archivo

    return _extraer_con_xml(archivo_bytes)


def _extraer_con_xml(archivo_bytes: BytesIO) -> tuple[dict[str, str], list[str]]:
    """Parseador directo de word/document.xml sin dependencias externas."""
    archivo_bytes.seek(0)
    try:
        with zipfile.ZipFile(archivo_bytes) as z:
            if 'word/document.xml' not in z.namelist():
                raise PlantillaInvalidaError('Formato .docx no válido: falta word/document.xml')
            # Rechazar documentos enormes antes de parsear (5 MB descomprimido)
            info = z.getinfo('word/document.xml')
            if info.file_size > 5 * 1024 * 1024:
                raise PlantillaInvalidaError('El documento supera el tamaño máximo permitido para su procesamiento.')
            xml_content = z.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as e:
        raise PlantillaInvalidaError('El archivo no es un archivo .docx válido.') from e

    root = ET.fromstring(xml_content)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

    datos: dict[str, str] = {}

    # --- Tablas (columna 1: etiqueta, columna 2: contenido) ---
    for tbl in root.findall('.//w:tbl', ns):
        for tr in tbl.findall('.//w:tr', ns):
            tcs = tr.findall('.//w:tc', ns)
            if len(tcs) >= 2:
                txt_col0 = ''.join(tcs[0].itertext()).strip()
                norm = normalizar_etiqueta(txt_col0)
                if norm in _LOOKUP:
                    campo = _LOOKUP[norm]
                    val = ''.join(tcs[1].itertext()).strip()
                    if val:
                        datos.setdefault(campo, val)

    # --- Párrafos con patrón "Etiqueta: valor" o etiqueta sola seguida de contenido ---
    clave_actual: str | None = None
    acumulado: dict[str, list[str]] = {}
    for p in root.findall('.//w:p', ns):
        texto = ''.join(p.itertext()).strip()
        if not texto:
            continue
        norm = normalizar_etiqueta(texto)
        if norm in _LOOKUP:
            clave_actual = _LOOKUP[norm]
            acumulado.setdefault(clave_actual, [])
            continue

        izq, sep, der = texto.partition(':')
        if sep and len(izq) <= 60 and normalizar_etiqueta(izq) in _LOOKUP:
            clave_actual = _LOOKUP[normalizar_etiqueta(izq)]
            acumulado.setdefault(clave_actual, [])
            if der.strip():
                acumulado[clave_actual].append(der.strip())
            continue

        if clave_actual:
            acumulado[clave_actual].append(texto)

    for campo, lineas in acumulado.items():
        if lineas:
            datos.setdefault(campo, '\n'.join(lineas).strip())

    datos = {k: v for k, v in datos.items() if v}

    # --- Validar que todas las etiquetas requeridas estén presentes ---
    campos_encontrados = set(datos.keys()) | {c for c in CAMPOS_PLANTILLA_REQUERIDOS if c in acumulado or c in datos}
    # Se considera "presente" si la etiqueta apareció aunque el valor esté vacío
    etiquetas_presentes: set[str] = set()
    for tbl in root.findall('.//w:tbl', ns):
        for tr in tbl.findall('.//w:tr', ns):
            tcs = tr.findall('.//w:tc', ns)
            if tcs:
                norm = normalizar_etiqueta(''.join(tcs[0].itertext()).strip())
                if norm in _LOOKUP:
                    etiquetas_presentes.add(_LOOKUP[norm])
    for p in root.findall('.//w:p', ns):
        texto = ''.join(p.itertext()).strip()
        norm = normalizar_etiqueta(texto)
        if norm in _LOOKUP:
            etiquetas_presentes.add(_LOOKUP[norm])
        izq, sep, _ = texto.partition(':')
        if sep and normalizar_etiqueta(izq) in _LOOKUP:
            etiquetas_presentes.add(_LOOKUP[normalizar_etiqueta(izq)])

    faltantes = CAMPOS_PLANTILLA_REQUERIDOS - etiquetas_presentes
    if faltantes:
        # Mapear de vuelta a nombres legibles para el mensaje
        nombre_por_campo = {v: k for k, v in ETIQUETAS_CAMPOS.items()}
        nombres_faltantes = ', '.join(sorted(nombre_por_campo.get(c, c) for c in faltantes))
        raise PlantillaInvalidaError(
            f'El archivo no corresponde a la plantilla de SISTRA o fue modificada su estructura. '
            f'Descarga la plantilla de nuevo. '
            f'(Etiquetas no encontradas: {nombres_faltantes})'
        )

    # --- Validar sector_entidad ---
    avisos: list[str] = []
    if 'sector_entidad' in datos:
        norm_sector = normalizar_etiqueta(datos['sector_entidad'])
        if norm_sector not in _SECTORES_VALIDOS:
            avisos.append(
                f'El valor «{datos["sector_entidad"]}» en «Sector de la entidad» no es válido '
                f'(debe ser Público o Privado). El campo quedó vacío para que lo selecciones.'
            )
            del datos['sector_entidad']

    return datos, avisos
