
import io
from datetime import date, datetime
from xml.sax.saxutils import escape

from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


def _texto_seguro(valor):
    """Convierte un valor en texto seguro para ReportLab."""
    if valor is None or valor == '':
        return '-'

    if isinstance(valor, datetime):
        valor = timezone.localtime(valor)
        return valor.strftime('%d/%m/%Y')

    if isinstance(valor, date):
        return valor.strftime('%d/%m/%Y')

    return escape(str(valor))


def _fecha_formato(valor):
    """Formatea fechas en DD/MM/AAAA usando la zona horaria local."""
    if not valor:
        return '-'

    if isinstance(valor, datetime):
        valor = timezone.localtime(valor)

    return valor.strftime('%d/%m/%Y')


def _parrafo(valor, estilo):
    """Crea un Paragraph escapando el contenido recibido."""
    return Paragraph(_texto_seguro(valor), estilo)


def _crear_estilos():
    """Define los estilos utilizados en el documento."""
    estilos = getSampleStyleSheet()

    estilos.add(ParagraphStyle(
        name='TituloReporte',
        parent=estilos['Title'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#1a365d'),
        spaceAfter=5,
    ))

    estilos.add(ParagraphStyle(
        name='SubtituloReporte',
        parent=estilos['Normal'],
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#4a5568'),
        spaceAfter=12,
    ))

    estilos.add(ParagraphStyle(
        name='CeldaReporte',
        parent=estilos['Normal'],
        fontName='Helvetica',
        fontSize=7,
        leading=9,
        alignment=TA_LEFT,
        wordWrap='CJK',
    ))

    estilos.add(ParagraphStyle(
        name='EncabezadoReporte',
        parent=estilos['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.white,
        wordWrap='CJK',
    ))

    estilos.add(ParagraphStyle(
        name='TituloSeccion',
        parent=estilos['Heading2'],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#1a365d'),
        spaceBefore=8,
        spaceAfter=7,
    ))

    return estilos


def _tabla(data, anchos, encabezado=True):
    """Aplica un formato común a las tablas del reporte."""
    ancho_disponible = landscape(letter)[0] - (24 * mm)
    ancho_total = sum(anchos)

    if ancho_total > ancho_disponible:
        factor = ancho_disponible / ancho_total
        anchos = [ancho * factor for ancho in anchos]

    tabla = Table(
        data,
        colWidths=anchos,
        repeatRows=1 if encabezado else 0,
        hAlign='LEFT',
    )

    instrucciones = [
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e0')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]

    if encabezado:
        instrucciones.extend([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a365d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ])

    tabla.setStyle(TableStyle(instrucciones))
    return tabla


def generar_pdf_trabajo_social(datos, rol_usuario, rango_fechas):
    """
    Genera el PDF consolidado de reportes de Trabajo Social.

    Incluye:
    - Resumen de estudiantes y entidades.
    - Detalle de propuestas aprobadas.
    - Consolidado de aprobados y rechazados.
    - Columna Carrera únicamente para usuarios con acceso global.
    """
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title='Reporte de Trabajo Social',
        author='Universidad de Pamplona - SISTRA',
    )

    estilos = _crear_estilos()
    elementos = []

    incluir_carrera = datos.get('incluir_carrera', False)

    fecha_desde = rango_fechas.get('start')
    fecha_hasta = rango_fechas.get('end')

    elementos.append(Paragraph(
        'UNIVERSIDAD DE PAMPLONA - SISTRA',
        estilos['TituloReporte'],
    ))

    elementos.append(Paragraph(
        'Reporte Consolidado de Trabajo Social',
        estilos['TituloReporte'],
    ))

    elementos.append(Paragraph(
        f'Rango: {_texto_seguro(fecha_desde)} a '
        f'{_texto_seguro(fecha_hasta)} | '
        f'Rol: {_texto_seguro(rol_usuario)}',
        estilos['SubtituloReporte'],
    ))

    resumen = datos.get('resumen', {})

    elementos.append(Paragraph(
        '1. Resumen general de aprobados',
        estilos['TituloSeccion'],
    ))

    resumen_data = [
        [
            _parrafo('Total estudiantes Trabajo Social', estilos['EncabezadoReporte']),
            _parrafo('Número entidades sector público', estilos['EncabezadoReporte']),
            _parrafo('Número entidades sector privado', estilos['EncabezadoReporte']),
        ],
        [
            _parrafo(resumen.get('total_estudiantes', 0), estilos['CeldaReporte']),
            _parrafo(resumen.get('entidades_publicas', 0), estilos['CeldaReporte']),
            _parrafo(resumen.get('entidades_privadas', 0), estilos['CeldaReporte']),
        ],
    ]

    elementos.append(_tabla(
        resumen_data,
        [85 * mm, 85 * mm, 85 * mm],
    ))

    elementos.append(Spacer(1, 8 * mm))

    # ---------------------------------------------------------
    # TABLA 1: PROPUESTAS APROBADAS
    # ---------------------------------------------------------

    elementos.append(Paragraph(
        '2. Detalle de propuestas aprobadas',
        estilos['TituloSeccion'],
    ))

    encabezados = [
        'Nro',
        'Nombres',
        'Título de la propuesta',
        'Entidad',
        'Población beneficiada',
        'Zona',
        'Área',
        'Sector',
        'Unidad',
    ]

    if incluir_carrera:
        encabezados.insert(2, 'Carrera')

    aprobados_data = [[
        _parrafo(titulo, estilos['EncabezadoReporte'])
        for titulo in encabezados
    ]]

    for indice, item in enumerate(datos.get('aprobados', []), start=1):
        fila = [
            _parrafo(indice, estilos['CeldaReporte']),
            _parrafo(item.get('nombre'), estilos['CeldaReporte']),
            _parrafo(item.get('titulo'), estilos['CeldaReporte']),
            _parrafo(item.get('entidad'), estilos['CeldaReporte']),
            _parrafo(item.get('poblacion_beneficiada'), estilos['CeldaReporte']),
            _parrafo(item.get('zona'), estilos['CeldaReporte']),
            _parrafo(item.get('area'), estilos['CeldaReporte']),
            _parrafo(item.get('sector'), estilos['CeldaReporte']),
            _parrafo(item.get('unidad'), estilos['CeldaReporte']),
        ]

        if incluir_carrera:
            fila.insert(
                2,
                _parrafo(item.get('carrera'), estilos['CeldaReporte']),
            )

        aprobados_data.append(fila)

    anchos_aprobados = [
        9 * mm,
        35 * mm,
        43 * mm,
        32 * mm,
        35 * mm,
        20 * mm,
        20 * mm,
        20 * mm,
        20 * mm,
    ]

    if incluir_carrera:
        anchos_aprobados.insert(2, 32 * mm)

    elementos.append(_tabla(aprobados_data, anchos_aprobados))

    elementos.append(Spacer(1, 8 * mm))

    # ---------------------------------------------------------
    # TABLA 2: APROBADOS Y RECHAZADOS
    # ---------------------------------------------------------

    total_aprobados = resumen.get('total_aprobados', 0)
    total_rechazados = resumen.get('total_rechazados', 0)

    elementos.append(Paragraph(
        '3. Consolidado de estados finales',
        estilos['TituloSeccion'],
    ))

    elementos.append(Paragraph(
        f'Total aprobados: {total_aprobados} | '
        f'Total rechazados: {total_rechazados}',
        estilos['Normal'],
    ))

    elementos.append(Spacer(1, 3 * mm))

    encabezados_finales = [
        'Nombres',
        'Cédula',
        'Estado final',
        'Fecha de envío',
        'Fecha de decisión',
        'Tipo de rechazo',
        'Observación',
    ]

    if incluir_carrera:
        encabezados_finales.insert(1, 'Carrera')

    finales_data = [[
        _parrafo(titulo, estilos['EncabezadoReporte'])
        for titulo in encabezados_finales
    ]]

    for item in datos.get('detalle_finales', []):
        fila = [
            _parrafo(item.get('nombre'), estilos['CeldaReporte']),
            _parrafo(item.get('cedula'), estilos['CeldaReporte']),
            _parrafo(item.get('estado_final'), estilos['CeldaReporte']),
            _parrafo(
                _fecha_formato(item.get('fecha_envio')),
                estilos['CeldaReporte'],
            ),
            _parrafo(
                _fecha_formato(item.get('fecha_decision')),
                estilos['CeldaReporte'],
            ),
            _parrafo(item.get('tipo_rechazo'), estilos['CeldaReporte']),
            _parrafo(item.get('observacion'), estilos['CeldaReporte']),
        ]

        if incluir_carrera:
            fila.insert(
                1,
                _parrafo(item.get('carrera'), estilos['CeldaReporte']),
            )

        finales_data.append(fila)

    anchos_finales = [
        38 * mm,
        25 * mm,
        28 * mm,
        25 * mm,
        25 * mm,
        35 * mm,
        65 * mm,
    ]

    if incluir_carrera:
        anchos_finales.insert(1, 32 * mm)

    elementos.append(_tabla(finales_data, anchos_finales))

    doc.build(elementos)

    buffer.seek(0)
    return buffer
