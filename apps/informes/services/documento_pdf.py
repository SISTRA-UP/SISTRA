"""Servicio de generación de PDF para Informes de Trabajo Social (B1b).

Reutiliza las funciones comunes de estilo y escape del módulo de reportes.
"""
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_LEFT

# Importamos las funciones comunes ya validadas en el sistema
from apps.reportes.services.report_pdf_service import (
    _texto_seguro,
    _fecha_formato,
    _parrafo,
    _crear_estilos,
)


def generar_pdf_informe(informe):
    """
    Genera el PDF del informe de trabajo social al momento, sin guardarlo en disco.
    
    Args:
        informe: Instancia del modelo Informe.
    
    Returns:
        io.BytesIO: Buffer con el contenido del PDF listo para ser servido.
    """
    buffer = io.BytesIO()

    # Usamos carta vertical (portrait) para documentos individuales
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f'Informe {informe.codigo}',
        author='Universidad de Pamplona - SISTRA',
    )

    estilos = _crear_estilos()
    elementos = []

    # Estilos específicos para el cuerpo del texto del informe
    estilo_cuerpo = estilos['Normal'].clone(
        'CuerpoInforme',
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=10,
    )

    estilo_label = estilos['Normal'].clone(
        'LabelInforme',
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
    )

    # 1. Encabezado
    elementos.append(Paragraph('UNIVERSIDAD DE PAMPLONA', estilos['TituloReporte']))
    elementos.append(Paragraph('INFORME DE TRABAJO SOCIAL', estilos['TituloReporte']))
    elementos.append(Paragraph(
        f'Código: {_texto_seguro(informe.codigo)} | Versión: {_texto_seguro(informe.version_entrega)}',
        estilos['SubtituloReporte']
    ))
    elementos.append(Spacer(1, 10 * mm))

    # 2. Información General
    elementos.append(Paragraph('1. Información General', estilos['TituloSeccion']))

    # Extraer datos del estudiante de forma segura
    try:
        estudiante = informe.propuesta.proceso.estudiante_carrera.estudiante
        usuario = estudiante.usuario
        carrera = informe.propuesta.proceso.estudiante_carrera.carrera.nombre
    except Exception:
        usuario = None
        carrera = 'No disponible'

    info_data = [
        ['Estudiante:', _texto_seguro(usuario.nombre if usuario else 'N/A')],
        ['Cédula:', _texto_seguro(usuario.cedula if usuario else 'N/A')],
        ['Carrera:', _texto_seguro(carrera)],
        ['Título de la Propuesta:', _texto_seguro(informe.propuesta.titulo)],
        ['Entidad:', _texto_seguro(informe.propuesta.entidad)],
        ['Periodo Académico:', _texto_seguro(informe.periodo_academico.nombre)],
        ['Fecha de Envío:', _fecha_formato(informe.fecha_envio)],
    ]

    info_tabla_data = [
        [_parrafo(label, estilo_label), _parrafo(valor, estilo_cuerpo)]
        for label, valor in info_data
    ]

    tabla_info = Table(info_tabla_data, colWidths=[60 * mm, 120 * mm], hAlign='LEFT')
    tabla_info.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elementos.append(tabla_info)
    elementos.append(Spacer(1, 8 * mm))

    # 3. Resultados
    elementos.append(Paragraph('2. Resultados', estilos['TituloSeccion']))
    elementos.append(_parrafo(informe.resultados or 'Sin resultados registrados.', estilo_cuerpo))
    elementos.append(Spacer(1, 8 * mm))

    # 4. Conclusiones
    elementos.append(Paragraph('3. Conclusiones', estilos['TituloSeccion']))
    elementos.append(_parrafo(informe.conclusiones or 'Sin conclusiones registradas.', estilo_cuerpo))
    elementos.append(Spacer(1, 8 * mm))

    # 5. Recomendaciones
    elementos.append(Paragraph('4. Recomendaciones', estilos['TituloSeccion']))
    elementos.append(_parrafo(informe.recomendaciones or 'Sin recomendaciones registradas.', estilo_cuerpo))

    # Construir el documento
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()