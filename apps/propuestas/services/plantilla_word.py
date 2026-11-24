"""SISTRA-01 · Generador de la plantilla oficial de propuesta en formato Word (.docx).

Genera el archivo .docx con la estructura OpenXML oficial conteniendo:
- Encabezado institucional de la Universidad de Pamplona y Trabajo Social.
- Tabla estructurada con las 16 etiquetas exactas de ETIQUETAS_CAMPOS.
- Etiquetas de fechas establecidas en la revisión R2 (Fecha estimada de inicio y finalización).
- Celdas para diligenciamiento por parte del estudiante.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any

from apps.propuestas.services.montaje import ETIQUETAS_CAMPOS, ETIQUETAS_FECHAS


def _escapar_xml(texto: Any) -> str:
    """Escapa caracteres para XML de Word."""
    if texto is None:
        return ""
    s = str(texto)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def generar_docx_plantilla_oficial(valores: dict[str, str] | None = None) -> bytes:
    """Genera en memoria los bytes del documento .docx oficial de la propuesta.

    Args:
        valores: Diccionario opcional {campo: valor} para pre-llenar las celdas
                 de diligenciamiento (por defecto contiene texto guía).

    Returns:
        bytes: Archivo .docx compatible con Microsoft Word y el lector XML de SISTRA.
    """
    if valores is None:
        valores = {}

    # Guías por defecto para cada campo si no se pasa valor
    guias_por_campo = {
        "titulo": "[Título claro y descriptivo del proyecto de Trabajo Social]",
        "entidad": "[Nombre de la entidad, institución u organización comunitaria]",
        "sector_entidad": "Público",
        "poblacion_beneficiada": "[Cantidad aproximada y características generales de los beneficiarios]",
        "identificacion_poblacion": "[Perfil sociodemográfico, vulnerabilidades y condiciones de la población]",
        "resena_historica": "[Antecedentes, origen y trayectoria institucional de la entidad]",
        "identificacion_necesidad": "[Planteamiento del problema central o necesidad comunitaria identificada]",
        "justificacion": "[Razones sociales, académicas e institucionales para intervenir]",
        "objetivos": "[Objetivo general y objetivos específicos del Trabajo Social]",
        "referente_teorico": "[Fundamentos conceptuales, legales y metodológicos]",
        "propuesta_social": "[Metodología, fases, actividades y estrategias planificadas]",
        "impacto_social": "[Transformaciones, beneficios o cambios esperados en la comunidad]",
        "zona": "Urbana",
        "area": "[Área temática de intervención]",
        "sector": "[Sector temático de aplicación]",
        "unidad": "[Barrio, vereda o dependencia ejecutora]",
        "fecha_inicio": "01/02/2026",
        "fecha_fin": "30/06/2026",
    }

    # Estructura del documento OpenXML
    ns = (
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    )

    # 1. Párrafos de encabezado institucional
    parrafos_header = [
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="1B365D"/></w:rPr><w:t>UNIVERSIDAD DE PAMPLONA</w:t></w:r></w:p>',
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="22"/><w:color w:val="334E68"/></w:rPr><w:t>SISTEMA DE SEGUIMIENTO Y TRÁMITES DE TRABAJO SOCIAL (SISTRA)</w:t></w:r></w:p>',
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="1B365D"/></w:rPr><w:t>FORMATO OFICIAL DE PROPUESTA DE TRABAJO SOCIAL</w:t></w:r></w:p>',
        '<w:p><w:pPr><w:jc w:val="both"/><w:spacing w:after="160"/></w:pPr><w:r><w:rPr><w:i/><w:sz w:val="18"/><w:color w:val="64748B"/></w:rPr><w:t>INSTRUCCIONES: Diligencie el contenido en la columna «Diligenciamiento del Estudiante». No modifique las etiquetas de la primera columna para permitir la lectura y autocompletado automático en la plataforma SISTRA.</w:t></w:r></w:p>',
    ]

    # 2. Filas de la tabla (16 etiquetas principales + fechas R2)
    filas_xml = [
        # Encabezado de tabla
        '<w:tr>'
        '<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="1B365D"/></w:tcPr>'
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="19"/><w:color w:val="FFFFFF"/></w:rPr><w:t>Etiqueta / Campo del Formulario</w:t></w:r></w:p>'
        '</w:tc>'
        '<w:tc><w:tcPr><w:tcW w:w="6000" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="1B365D"/></w:tcPr>'
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="19"/><w:color w:val="FFFFFF"/></w:rPr><w:t>Diligenciamiento del Estudiante</w:t></w:r></w:p>'
        '</w:tc>'
        '</w:tr>'
    ]

    lista_etiquetas: list[tuple[str, str]] = list(ETIQUETAS_CAMPOS.items())
    lista_etiquetas.append(("Fecha estimada de inicio", "fecha_inicio"))
    lista_etiquetas.append(("Fecha estimada de finalización", "fecha_fin"))

    for i, (etiqueta, campo) in enumerate(lista_etiquetas):
        fill_color = "EBF3FB" if i % 2 == 0 else "F8FAFC"
        contenido = valores.get(campo, guias_por_campo.get(campo, ""))
        etiqueta_esc = _escapar_xml(etiqueta)
        contenido_esc = _escapar_xml(contenido)

        fila = (
            f'<w:tr>'
            f'<w:tc><w:tcPr><w:tcW w:w="3000" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="{fill_color}"/></w:tcPr>'
            f'<w:p><w:r><w:rPr><w:b/><w:sz w:val="19"/><w:color w:val="1B365D"/></w:rPr><w:t>{etiqueta_esc}</w:t></w:r></w:p>'
            f'</w:tc>'
            f'<w:tc><w:tcPr><w:tcW w:w="6000" w:type="dxa"/></w:tcPr>'
            f'<w:p><w:r><w:rPr><w:sz w:val="19"/><w:color w:val="1E293B"/></w:rPr><w:t>{contenido_esc}</w:t></w:r></w:p>'
            f'</w:tc>'
            f'</w:tr>'
        )
        filas_xml.append(fila)

    tabla_xml = (
        '<w:tbl>'
        '<w:tblPr>'
        '<w:tblW w:w="9000" w:type="dxa"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '</w:tblBorders>'
        '</w:tblPr>'
        + "".join(filas_xml)
        + '</w:tbl>'
    )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document {ns}>'
        '<w:body>'
        + "".join(parrafos_header)
        + tabla_xml
        + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
        '</w:body>'
        '</w:document>'
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types_xml.encode("utf-8"))
        z.writestr("_rels/.rels", rels_xml.encode("utf-8"))
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))

    return buf.getvalue()
