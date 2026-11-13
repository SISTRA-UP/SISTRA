"""SISTRA-01 · Montaje de propuesta: servicio de extracción de plantilla Word.

Soporta lectura mediante python-docx si está disponible, o mediante parseo
nativo de document.xml (zipfile) para entornos donde python-docx no esté instalado.
"""
from io import BytesIO
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile


class PlantillaInvalidaError(Exception):
    """El archivo no es una plantilla Word (.docx) válida o legible."""


# Mapeo de campos del modelo Propuesta a etiquetas en español usadas en la plantilla
ETIQUETAS_CAMPOS = {
    'titulo': ['titulo', 'titulo de la propuesta', 'nombre del proyecto', 'proyecto'],
    'entidad': ['entidad', 'entidad beneficiaria', 'institucion', 'organizacion', 'empresa'],
    'sector_entidad': ['sector entidad', 'tipo entidad', 'sector institucional'],
    'sector': ['sector', 'sector social', 'area social'],
    'zona': ['zona', 'ubicacion zona'],
    'area': ['area', 'area tematica'],
    'unidad': ['unidad', 'unidad ejecutora', 'barrio', 'comuna'],
    'poblacion_beneficiada': ['poblacion beneficiada', 'poblacion beneficiaria', 'beneficiarios', 'numero de beneficiarios'],
    'identificacion_poblacion': ['identificacion de la poblacion', 'poblacion objetivo', 'caracteristicas de la poblacion'],
    'resena_historica': ['resena historica', 'antecedentes', 'contexto historico'],
    'identificacion_necesidad': ['identificacion de la necesidad', 'descripcion del problema', 'planteamiento del problema', 'problema'],
    'justificacion': ['justificacion', 'porque se realiza el proyecto'],
    'objetivos': ['objetivos', 'objetivo general', 'objetivos especificos'],
    'referente_teorico': ['referente teorico', 'marco teorico', 'marco conceptual'],
    'propuesta_social': ['propuesta social', 'metodologia', 'plan de trabajo', 'actividades'],
    'impacto_social': ['impacto social', 'impacto esperado', 'resultados esperados'],
}

_LOOKUP = {
    _norm: campo
    for campo, variantes in ETIQUETAS_CAMPOS.items()
    for _norm in [unicodedata.normalize('NFKD', v).encode('ASCII', 'ignore').decode().lower().strip() for v in variantes]
}


def normalizar_etiqueta(texto: str) -> str:
    """Normaliza texto removiendo tildes, mayúsculas y caracteres de puntuación."""
    t = unicodedata.normalize('NFKD', texto or '').encode('ASCII', 'ignore').decode().lower()
    return re.sub(r'[\s:._\-]+', ' ', t).strip()


def extraer_datos_plantilla(archivo) -> dict[str, str]:
    """Extrae pares campo -> texto desde un archivo .docx."""
    if hasattr(archivo, 'read'):
        contenido = archivo.read()
        archivo_bytes = BytesIO(contenido)
    else:
        archivo_bytes = archivo

    # Intentar con python-docx si está instalado
    try:
        from docx import Document
        return _extraer_con_docx(archivo_bytes)
    except ImportError:
        return _extraer_con_xml(archivo_bytes)
    except Exception as exc:
        # Fallback a XML directo ante cualquier error de python-docx
        try:
            archivo_bytes.seek(0)
            return _extraer_con_xml(archivo_bytes)
        except Exception:
            raise PlantillaInvalidaError('El archivo no es una plantilla .docx legible.') from exc


def _extraer_con_docx(archivo_bytes) -> dict[str, str]:
    from docx import Document
    archivo_bytes.seek(0)
    doc = Document(archivo_bytes)
    datos: dict[str, str] = {}

    # 1. Búsqueda en tablas (columna 1: etiqueta, columna 2: contenido)
    for tabla in doc.tables:
        for fila in tabla.rows:
            celdas = [c.text.strip() for c in fila.cells]
            if len(celdas) >= 2:
                clave = normalizar_etiqueta(celdas[0])
                if clave in _LOOKUP:
                    campo = _LOOKUP[clave]
                    valor = celdas[1].strip()
                    if valor:
                        datos.setdefault(campo, valor)

    # 2. Búsqueda en párrafos
    clave_actual = None
    acumulado: dict[str, list[str]] = {}
    for p in doc.paragraphs:
        texto = p.text.strip()
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

    return {k: v for k, v in datos.items() if v}


def _extraer_con_xml(archivo_bytes) -> dict[str, str]:
    """Parseador directo de word/document.xml sin dependencias externas."""
    archivo_bytes.seek(0)
    try:
        with zipfile.ZipFile(archivo_bytes) as z:
            if 'word/document.xml' not in z.namelist():
                raise PlantillaInvalidaError('Formato .docx no válido: falta word/document.xml')
            xml_content = z.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as e:
        raise PlantillaInvalidaError('El archivo no es un archivo .docx válido.') from e

    root = ET.fromstring(xml_content)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

    datos: dict[str, str] = {}

    # Tablas
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

    # Párrafos
    clave_actual = None
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

    return {k: v for k, v in datos.items() if v}

