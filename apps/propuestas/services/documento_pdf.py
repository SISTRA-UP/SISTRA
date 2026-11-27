"""SISTRA-01 · Generación de documento PDF oficial de la propuesta de Trabajo Social.

Genera en memoria (sin persistir en disco ni base de datos, decisión M4)
el PDF oficial con:
- Código, Estudiante, Carrera, Periodo académico.
- Fechas de inicio y fin (o indicador si no están definidas).
- Los 16 campos oficiales del formulario de Trabajo Social.
- Cronograma de actividades (si existen actividades registradas).

Las partes comunes (estilos, encabezado, tabla de campos) quedan modularizadas
en funciones públicas reutilizables para que puedan ser aprovechadas en otros
documentos del sistema, tales como el informe de Trabajo Social (RG-10).
"""

from __future__ import annotations

import io
from functools import partial
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from apps.propuestas.services.montaje import ETIQUETAS_CAMPOS

# ---------------------------------------------------------------------------
# Definición de los 16 campos oficiales del formulario (SISTRA-01)
# ---------------------------------------------------------------------------
# Las mismas 16 etiquetas que lee la plantilla Word, en el mismo orden.
CAMPOS_FORMULARIO_PROPUESTA: tuple[tuple[str, str], ...] = tuple(ETIQUETAS_CAMPOS.items())

# Paleta institucional SISTRA / Universidad de Pamplona
COLOR_PRIMARIO = colors.HexColor("#1B365D")      # Azul marino institucional
COLOR_SECUNDARIO = colors.HexColor("#334E68")    # Azul medio
COLOR_FONDO_CABECERA = colors.HexColor("#EBF3FB")# Azul muy claro
COLOR_FONDO_ALT = colors.HexColor("#F8FAFC")     # Gris azulado tenue
COLOR_BORDE = colors.HexColor("#CBD5E1")         # Gris suave para líneas
COLOR_TEXTO = colors.HexColor("#1E293B")         # Carbón legible


# ---------------------------------------------------------------------------
# Escape y saneamiento de textos
# ---------------------------------------------------------------------------
def _texto_seguro(texto: Any) -> str:
    """Sanea y escapa texto para evitar errores de sintaxis XML en ReportLab Paragraph.

    Reemplaza caracteres especiales (&, <, >, ", ') por sus entidades XML correspondientes,
    permitiendo que caracteres como '<b>' o '&' introducidos por el usuario se impriman
    literalmente en el documento final. También preserva saltos de línea sustituyendo \\n
    por <br/>.
    """
    if texto is None:
        return ""
    s = str(texto)
    # Escapar ampersand primero para no re-escapar entidades
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#39;")
    s = s.replace("\r\n", "<br/>").replace("\n", "<br/>")
    return s


def _formatear_fecha(fecha: Any) -> str:
    """Formatea fechas de manera segura tolerando None o cadenas."""
    if not fecha:
        return "No definida"
    if hasattr(fecha, "strftime"):
        return fecha.strftime("%d/%m/%Y")
    return str(fecha)


def _obtener_nombre_estudiante(propuesta: Any) -> str:
    """Obtiene el nombre completo del estudiante desde la relación con ProcesoTrabajoSocial."""
    proceso = getattr(propuesta, "proceso", None)
    ec = getattr(proceso, "estudiante_carrera", None) if proceso is not None else None
    est = getattr(ec, "estudiante", None) if ec is not None else None
    usuario = getattr(est, "usuario", None) if est is not None else None
    nombre = getattr(usuario, "nombre", None) if usuario is not None else None
    if isinstance(nombre, str) and nombre.strip():
        return nombre.strip()
    return "No asignado"


def _obtener_nombre_carrera(propuesta: Any) -> str:
    """Obtiene el nombre de la carrera desde la relación con ProcesoTrabajoSocial."""
    proceso = getattr(propuesta, "proceso", None)
    ec = getattr(proceso, "estudiante_carrera", None) if proceso is not None else None
    carrera = getattr(ec, "carrera", None) if ec is not None else None
    nombre = getattr(carrera, "nombre", None) if carrera is not None else None
    if isinstance(nombre, str) and nombre.strip():
        return nombre.strip()
    return "No asignada"


def _obtener_nombre_periodo(propuesta: Any) -> str:
    """Obtiene el nombre del periodo académico asociado a la propuesta."""
    periodo = getattr(propuesta, "periodo_academico", None)
    nombre = getattr(periodo, "nombre", None) if periodo is not None else None
    if isinstance(nombre, str) and nombre.strip():
        return nombre.strip()
    return "No asignado"


# ---------------------------------------------------------------------------
# Partes comunes reutilizables (para Propuesta y para Informe RG-10)
# ---------------------------------------------------------------------------
def obtener_estilos_pdf() -> dict[str, ParagraphStyle]:
    """Genera y retorna un diccionario de estilos tipográficos para los documentos PDF."""
    estilos_base = getSampleStyleSheet()

    estilos: dict[str, ParagraphStyle] = {
        "Titulo": ParagraphStyle(
            "SistraTitulo",
            parent=estilos_base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=COLOR_PRIMARIO,
            alignment=1,  # Centrado
            spaceAfter=4,
        ),
        "Subtitulo": ParagraphStyle(
            "SistraSubtitulo",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=COLOR_SECUNDARIO,
            alignment=1,
            spaceAfter=12,
        ),
        "Seccion": ParagraphStyle(
            "SistraSeccion",
            parent=estilos_base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=COLOR_PRIMARIO,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "MetaEtiqueta": ParagraphStyle(
            "SistraMetaEtiqueta",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=COLOR_PRIMARIO,
        ),
        "MetaValor": ParagraphStyle(
            "SistraMetaValor",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=COLOR_TEXTO,
        ),
        "CampoTitulo": ParagraphStyle(
            "SistraCampoTitulo",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=COLOR_PRIMARIO,
        ),
        "CampoContenido": ParagraphStyle(
            "SistraCampoContenido",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=COLOR_TEXTO,
        ),
        "TablaHeader": ParagraphStyle(
            "SistraTablaHeader",
            parent=estilos_base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
            alignment=1,
        ),
        "TablaCelda": ParagraphStyle(
            "SistraTablaCelda",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=COLOR_TEXTO,
        ),
        "TablaCeldaCentro": ParagraphStyle(
            "SistraTablaCeldaCentro",
            parent=estilos_base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=COLOR_TEXTO,
            alignment=1,
        ),
    }

    return estilos


def construir_encabezado_pdf(
    titulo: str,
    subtitulo: str,
    metadatos: list[tuple[str, str]],
    estilos: dict[str, ParagraphStyle] | None = None,
) -> list[Any]:
    """Construye los flowables del encabezado del documento y la tabla de metadatos.

    Args:
        titulo: Título principal (p.ej. 'PROPUESTA DE TRABAJO SOCIAL').
        subtitulo: Subtítulo o texto institucional.
        metadatos: Pares de (Etiqueta, Valor) informativos (código, estudiante, carrera, etc.).
        estilos: Diccionario de ParagraphStyle (opcional, usa obtener_estilos_pdf() por defecto).

    Returns:
        Lista de Flowables listos para agregar a la historia de ReportLab.
    """
    if estilos is None:
        estilos = obtener_estilos_pdf()

    elementos: list[Any] = []
    elementos.append(Paragraph(_texto_seguro(titulo), estilos["Titulo"]))
    elementos.append(Paragraph(_texto_seguro(subtitulo), estilos["Subtitulo"]))
    elementos.append(
        HRFlowable(
            width="100%",
            thickness=1.5,
            color=COLOR_PRIMARIO,
            spaceBefore=0,
            spaceAfter=8,
        )
    )

    if metadatos:
        filas_tabla: list[list[Any]] = []
        # Agrupar metadatos en pares de 2 columnas (Etiqueta 1, Valor 1, Etiqueta 2, Valor 2)
        for i in range(0, len(metadatos), 2):
            par1 = metadatos[i]
            par2 = metadatos[i + 1] if i + 1 < len(metadatos) else ("", "")

            celda_lbl1 = Paragraph(f"<b>{_texto_seguro(par1[0])}:</b>", estilos["MetaEtiqueta"]) if par1[0] else ""
            celda_val1 = Paragraph(_texto_seguro(par1[1]), estilos["MetaValor"]) if par1[0] else ""

            celda_lbl2 = Paragraph(f"<b>{_texto_seguro(par2[0])}:</b>", estilos["MetaEtiqueta"]) if par2[0] else ""
            celda_val2 = Paragraph(_texto_seguro(par2[1]), estilos["MetaValor"]) if par2[0] else ""

            filas_tabla.append([celda_lbl1, celda_val1, celda_lbl2, celda_val2])

        # Ancho total: 540 pt (8.5 * 72 = 612 - 72 de márgenes = 540 pt)
        tabla_meta = Table(filas_tabla, colWidths=[90, 180, 90, 180])
        tabla_meta.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, -1), COLOR_FONDO_ALT),
                    ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDE),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, COLOR_BORDE),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elementos.append(tabla_meta)
        elementos.append(Spacer(1, 10))

    return elementos


def construir_tabla_campos(
    campos: list[tuple[str, str]],
    estilos: dict[str, ParagraphStyle] | None = None,
) -> list[Any]:
    """Construye los bloques visuales para la lista de campos (Etiqueta, Valor).

    Cada campo se presenta como una tarjeta compacta con una franja de encabezado
    con el nombre del campo y el bloque de contenido debajo. Si el valor está vacío,
    se muestra un guion largo (—).
    """
    if estilos is None:
        estilos = obtener_estilos_pdf()

    elementos: list[Any] = []

    for etiqueta, valor in campos:
        contenido = (str(valor).strip() if valor is not None else "") or "—"
        encabezado = Table(
            [[Paragraph(f"<b>{_texto_seguro(etiqueta)}</b>", estilos["CampoTitulo"])]],
            colWidths=[540],
        )
        encabezado.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), COLOR_FONDO_CABECERA),
                    ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDE),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        # El contenido va como párrafo suelto, no dentro de la tabla:
        # así puede seguir en la página siguiente si el texto es largo.
        cuerpo = Paragraph(_texto_seguro(contenido), estilos["CampoContenido"])
        bloque = [encabezado, Spacer(1, 4), cuerpo, Spacer(1, 8)]
        _, alto = cuerpo.wrap(540, 10_000)
        if alto < 250:
            # Un campo corto no se parte entre dos páginas.
            elementos.append(KeepTogether(bloque))
        else:
            # Uno largo empieza donde va y sigue en la página siguiente.
            elementos.extend(bloque)

    return elementos


def construir_tabla_cronograma(
    actividades: Any,
    estilos: dict[str, ParagraphStyle] | None = None,
) -> list[Any]:
    """Construye la sección y tabla del cronograma si existen actividades.

    Si la colección de actividades es nula o vacía, retorna una lista vacía.
    """
    if not actividades:
        return []

    # Verificar si es iterable no vacío
    try:
        lista_actividades = list(actividades)
    except TypeError:
        return []

    if not lista_actividades:
        return []

    if estilos is None:
        estilos = obtener_estilos_pdf()

    elementos: list[Any] = []
    elementos.append(Spacer(1, 8))
    elementos.append(Paragraph("CRONOGRAMA DE ACTIVIDADES", estilos["Seccion"]))

    filas: list[list[Any]] = [
        [
            Paragraph("<b>#</b>", estilos["TablaHeader"]),
            Paragraph("<b>Actividad</b>", estilos["TablaHeader"]),
            Paragraph("<b>Descripción</b>", estilos["TablaHeader"]),
            Paragraph("<b>Inicio</b>", estilos["TablaHeader"]),
            Paragraph("<b>Fin</b>", estilos["TablaHeader"]),
            Paragraph("<b>Responsable</b>", estilos["TablaHeader"]),
        ]
    ]

    for act in lista_actividades:
        orden = getattr(act, "orden", "")
        nombre = getattr(act, "nombre", "")
        desc = getattr(act, "descripcion", "") or "—"
        f_inicio = _formatear_fecha(getattr(act, "fecha_inicio", None))
        f_fin = _formatear_fecha(getattr(act, "fecha_fin", None))
        resp = getattr(act, "responsable", "") or "—"

        filas.append(
            [
                Paragraph(_texto_seguro(orden), estilos["TablaCeldaCentro"]),
                Paragraph(_texto_seguro(nombre), estilos["TablaCelda"]),
                Paragraph(_texto_seguro(desc), estilos["TablaCelda"]),
                Paragraph(_texto_seguro(f_inicio), estilos["TablaCeldaCentro"]),
                Paragraph(_texto_seguro(f_fin), estilos["TablaCeldaCentro"]),
                Paragraph(_texto_seguro(resp), estilos["TablaCelda"]),
            ]
        )

    # Anchos: [24, 110, 160, 68, 68, 110] = 540 pt
    tabla_cronograma = Table(filas, colWidths=[24, 110, 160, 68, 68, 110], repeatRows=1)
    tabla_cronograma.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARIO),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.5, COLOR_BORDE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_FONDO_ALT]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elementos.append(tabla_cronograma)
    elementos.append(Spacer(1, 10))

    return elementos


# ---------------------------------------------------------------------------
# Canvas con numeración de páginas y pie institucional
# ---------------------------------------------------------------------------
class _CanvasConNumeracion(canvas.Canvas):
    """Canvas de ReportLab que calcula el número total de páginas en dos pasadas."""

    def __init__(
        self,
        *args: Any,
        pie_texto: str = "SISTRA · Universidad de Pamplona",
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._pie_texto = pie_texto
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_paginas = len(self._saved_page_states)
        for estado in self._saved_page_states:
            self.__dict__.update(estado)
            self._dibujar_pie(num_paginas)
            super().showPage()
        super().save()

    def _dibujar_pie(self, total_paginas: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Línea divisoria inferior
        self.setStrokeColor(COLOR_BORDE)
        self.setLineWidth(0.5)
        self.line(36, 32, 576, 32)

        texto_izq = self._pie_texto or "SISTRA · Universidad de Pamplona"
        texto_der = f"Página {self._pageNumber} de {total_paginas}"

        self.drawString(36, 20, texto_izq)
        self.drawRightString(576, 20, texto_der)
        self.restoreState()


def construir_documento_pdf(
    historia: list[Any],
    pie_texto: str = "SISTRA · Universidad de Pamplona",
) -> bytes:
    """Crea el documento PDF tamaño carta con márgenes estándar y numeración de páginas.

    Función común reutilizable para Propuesta e Informe de Trabajo Social (RG-10).

    Args:
        historia: Lista de Flowables de ReportLab que componen el cuerpo del documento.
        pie_texto: Texto institucional que aparece a la izquierda del pie de página.

    Returns:
        bytes: Contenido binario del documento PDF generado en memoria.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=45,
    )
    doc.build(
        historia,
        canvasmaker=partial(_CanvasConNumeracion, pie_texto=pie_texto),
    )
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Función principal de generación
# ---------------------------------------------------------------------------
def generar_pdf_propuesta(propuesta: Any) -> bytes:
    """Genera los bytes del documento PDF oficial para una propuesta de Trabajo Social.

    Incluye:
    - Código oficial de la propuesta.
    - Datos del estudiante, carrera y periodo académico.
    - Fechas de inicio y fin (o 'No definida' si están en blanco).
    - Los 16 campos oficiales del formulario de la propuesta.
    - Cronograma de actividades planificadas si existe.

    El PDF se genera en memoria al vuelo y nunca se guarda en disco ni en base
    de datos (decisión arquitectónica M4).

    Args:
        propuesta: Instancia de Propuesta con sus atributos y relaciones.

    Returns:
        bytes: Contenido binario del documento PDF generado.
    """
    estilos = obtener_estilos_pdf()
    historia: list[Any] = []

    # 1. Metadatos del encabezado
    codigo = getattr(propuesta, "codigo", "") or "Sin código"
    estudiante = _obtener_nombre_estudiante(propuesta)
    carrera = _obtener_nombre_carrera(propuesta)
    periodo = _obtener_nombre_periodo(propuesta)
    fecha_inicio = _formatear_fecha(getattr(propuesta, "fecha_inicio", None))
    fecha_fin = _formatear_fecha(getattr(propuesta, "fecha_fin", None))

    metadatos = [
        ("Código", codigo),
        ("Estudiante", estudiante),
        ("Carrera", carrera),
        ("Periodo académico", periodo),
        ("Fecha estimada de inicio", fecha_inicio),
        ("Fecha estimada de finalización", fecha_fin),
    ]

    historia.extend(
        construir_encabezado_pdf(
            titulo="PROPUESTA DE TRABAJO SOCIAL",
            subtitulo="Sistema de Seguimiento y Trámites de Trabajo Social (SISTRA)",
            metadatos=metadatos,
            estilos=estilos,
        )
    )

    # 2. Extracción de los 16 campos oficiales
    campos_extraidos: list[tuple[str, str]] = []
    for etiqueta, nombre_campo in CAMPOS_FORMULARIO_PROPUESTA:
        valor = getattr(propuesta, nombre_campo, "")
        campos_extraidos.append((etiqueta, valor))

    historia.append(Paragraph("DETALLE DE LA PROPUESTA", estilos["Seccion"]))
    historia.extend(construir_tabla_campos(campos_extraidos, estilos=estilos))

    # 3. Cronograma de actividades si existe
    crono_rel = getattr(propuesta, "cronograma", None)
    if crono_rel is not None and hasattr(crono_rel, "all"):
        actividades = crono_rel.all().order_by("orden")
        if actividades:
            historia.extend(construir_tabla_cronograma(actividades, estilos=estilos))

    # 4. Compilar documento en memoria
    return construir_documento_pdf(
        historia,
        pie_texto="SISTRA · Universidad de Pamplona — Propuesta de Trabajo Social",
    )
