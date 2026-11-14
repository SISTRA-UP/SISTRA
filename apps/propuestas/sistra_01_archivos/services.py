"""
services.py — Parseador de plantilla Word (python-docx) y utilidades del módulo.

Soporta dos formatos de plantilla:
  1) Tabla de dos columnas:  | Etiqueta | Contenido |
  2) Párrafos: un párrafo con la etiqueta (o "Etiqueta: valor" en una línea)
     seguido del contenido hasta la siguiente etiqueta.
"""
import re
import unicodedata
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from .models import Sector


class PlantillaInvalidaError(Exception):
    """El archivo no es una plantilla .docx legible."""


# campo del modelo -> etiquetas aceptadas en la plantilla (normalizadas: sin tildes ni mayúsculas)
ETIQUETAS = {
    "titulo": ["titulo", "titulo de la propuesta", "nombre del proyecto"],
    "entidad": ["entidad", "entidad beneficiaria", "institucion", "organizacion"],
    "sector": ["sector"],
    "poblacion_beneficiada": ["poblacion beneficiada", "poblacion beneficiaria", "beneficiarios"],
    "impacto_social": ["impacto social", "impacto"],
    "descripcion_problema": ["descripcion del problema", "planteamiento del problema", "problema"],
    "justificacion": ["justificacion"],
    "objetivo_general": ["objetivo general"],
    "objetivos_especificos": ["objetivos especificos"],
    "metodologia": ["metodologia"],
}
_LOOKUP = {etq: campo for campo, etqs in ETIQUETAS.items() for etq in etqs}


def _norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip(" :.\t\n").lower()


def _normalizar_sector(valor: str) -> str:
    """Convierte el texto libre de la plantilla en un valor válido de Sector ('' si no coincide)."""
    v = _norm(valor)
    for codigo, etiqueta in Sector.choices:
        if v in (_norm(codigo), _norm(etiqueta)):
            return codigo
    return ""


def extraer_datos_plantilla(archivo) -> dict:
    """
    Lee un .docx y devuelve {campo_modelo: texto} solo con los campos encontrados y no vacíos.
    Lanza PlantillaInvalidaError si el archivo no es un Word válido.
    """
    try:
        doc = Document(archivo)
    except (PackageNotFoundError, BadZipFile, KeyError, ValueError) as exc:
        raise PlantillaInvalidaError("El archivo no es una plantilla de Word (.docx) válida.") from exc

    datos: dict[str, str] = {}

    # 1) Tablas etiqueta | contenido
    for tabla in doc.tables:
        for fila in tabla.rows:
            celdas = [c.text.strip() for c in fila.cells]
            if len(celdas) >= 2 and _norm(celdas[0]) in _LOOKUP:
                valor = next((c for c in celdas[1:] if c), "")
                datos.setdefault(_LOOKUP[_norm(celdas[0])], valor)

    # 2) Párrafos
    actual = None
    acumulado: dict[str, list[str]] = {}
    for p in doc.paragraphs:
        texto = p.text.strip()
        if not texto:
            continue
        if _norm(texto) in _LOOKUP:                       # párrafo que es solo la etiqueta
            actual = _LOOKUP[_norm(texto)]
            acumulado.setdefault(actual, [])
            continue
        izquierda, sep, derecha = texto.partition(":")     # "Etiqueta: valor"
        if sep and len(izquierda) <= 60 and _norm(izquierda) in _LOOKUP:
            actual = _LOOKUP[_norm(izquierda)]
            acumulado.setdefault(actual, [])
            if derecha.strip():
                acumulado[actual].append(derecha.strip())
            continue
        if actual:
            acumulado[actual].append(texto)

    for campo, lineas in acumulado.items():
        if lineas:
            datos.setdefault(campo, "\n".join(lineas))

    if "sector" in datos:
        sector = _normalizar_sector(datos["sector"])
        if sector:
            datos["sector"] = sector
        else:
            datos.pop("sector")

    return {k: v.strip() for k, v in datos.items() if v and v.strip()}


def obtener_director(usuario):
    """
    Punto de integración: devuelve el Director asignado al estudiante.
    Ajusta a tu modelo de perfil, p. ej. `usuario.perfil_estudiante.director`.
    """
    return getattr(usuario, "director_asignado", None)
