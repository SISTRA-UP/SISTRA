import io
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generar_pdf_trabajo_social(datos, rol_usuario, rango_fechas):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=14, textColor=colors.HexColor('#1a365d'), spaceAfter=8)
    sub_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#4a5568'), spaceAfter=15)

    elements.append(Paragraph("UNIVERSIDAD DE PAMPLONA - SISTRA", title_style))
    elements.append(Paragraph("Reporte Consolidado de Trabajo Social", title_style))
    elements.append(Paragraph(f"Rango: {rango_fechas.get('start', 'N/A')} a {rango_fechas.get('end', 'N/A')} | Rol: {rol_usuario}", sub_style))
    elements.append(Spacer(1, 10))

    resumen = datos.get('resumen') or {}
    resumen_data = [
        ['Total Estudiantes Trabajo Social', 'Entidades Sector Público', 'Entidades Sector Privado'],
        [str(resumen.get('total_estudiantes', 0)), str(resumen.get('entidades_publicas', 0)), str(resumen.get('entidades_privadas', 0))]
    ]
    t_resumen = Table(resumen_data, colWidths=[200, 200, 200])
    t_resumen.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2b6cb0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e0')),
    ]))
    elements.append(t_resumen)
    elements.append(Spacer(1, 15))

    detalle_data = [['Nro', 'Nombres', 'Semestre', 'Título Propuesta', 'Entidad', 'Población', 'Impacto (Zona / Área / Sector / Unidad)']]
    
    for idx, item in enumerate(datos.get('detalle', []), 1):
        impacto_str = f"{item.impacto_zona} / {item.impacto_area} / {item.impacto_sector} / {item.impacto_unidad}"
        detalle_data.append([
            str(idx), str(item.estudiante.get_full_name()), str(item.semestre),
            str(item.titulo), str(item.entidad.nombre), str(item.poblacion_beneficiada), impacto_str
        ])

    t_detalle = Table(detalle_data, colWidths=[30, 120, 50, 150, 100, 100, 190])
    t_detalle.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a202c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(t_detalle)

    doc.build(elements)
    buffer.seek(0)
    return buffer