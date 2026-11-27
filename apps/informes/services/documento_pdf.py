"""SISTRA-06 · Generación de documento PDF oficial del informe de Trabajo Social.

Genera en memoria (sin persistir en disco ni base de datos, decisión M4)
el PDF oficial del informe reutilizando las partes comunes de B1a (RG-10).
"""

from typing import Any

from apps.propuestas.services.documento_pdf import (
    construir_documento_pdf,
    construir_encabezado_pdf,
    construir_tabla_campos,
    obtener_estilos_pdf,
    _obtener_nombre_periodo,
    _formatear_fecha,
)


def generar_pdf_informe(informe: Any) -> bytes:
    """
    Genera los bytes del documento PDF oficial para un informe de Trabajo Social.

    Incluye:
    - Código y versión del informe.
    - Datos del estudiante (nombre y cédula), carrera y periodo académico.
    - Título de la propuesta y entidad.
    - Fecha de envío.
    - Los 3 campos principales: Resultados, Conclusiones y Recomendaciones.

    El PDF se genera en memoria al vuelo y nunca se guarda en disco ni en base
    de datos (decisión arquitectónica M4).

    Args:
        informe: Instancia del modelo Informe con sus relaciones cargadas.

    Returns:
        bytes: Contenido binario del documento PDF generado en memoria.
    """
    estilos = obtener_estilos_pdf()
    historia: list[Any] = []

    # 1. Extraer metadatos de forma segura
    codigo = getattr(informe, "codigo", "") or "Sin código"
    version = getattr(informe, "version_entrega", 1)
    
    cedula = "No asignada"
    estudiante_nombre = "No asignado"
    carrera_nombre = "No asignada"
    
    try:
        proceso = getattr(informe.propuesta, "proceso", None)
        if proceso:
            ec = getattr(proceso, "estudiante_carrera", None)
            if ec:
                estudiante = getattr(ec, "estudiante", None)
                if estudiante:
                    usuario = getattr(estudiante, "usuario", None)
                    if usuario:
                        estudiante_nombre = getattr(usuario, "nombre", "No asignado") or "No asignado"
                        cedula = getattr(usuario, "cedula", "No asignada") or "No asignada"
                carrera = getattr(ec, "carrera", None)
                if carrera:
                    carrera_nombre = getattr(carrera, "nombre", "No asignada") or "No asignada"
    except Exception:
        pass

    periodo = _obtener_nombre_periodo(informe.propuesta)
    fecha_envio = _formatear_fecha(getattr(informe, "fecha_envio", None))
    titulo_propuesta = getattr(informe.propuesta, "titulo", "") or "Sin título"
    entidad = getattr(informe.propuesta, "entidad", "") or "Sin entidad"

    metadatos = [
        ("Código", f"{codigo} (v{version})"),
        ("Estudiante", estudiante_nombre),
        ("Cédula", cedula),
        ("Carrera", carrera_nombre),
        ("Periodo académico", periodo),
        ("Título de la propuesta", titulo_propuesta),
        ("Entidad", entidad),
        ("Fecha de envío", fecha_envio),
    ]

    # 2. Construir encabezado (aplica _texto_seguro internamente una sola vez)
    historia.extend(
        construir_encabezado_pdf(
            titulo="UNIVERSIDAD DE PAMPLONA",
            subtitulo="INFORME DE TRABAJO SOCIAL",
            metadatos=metadatos,
            estilos=estilos,
        )
    )

    # 3. Campos del informe (aplica _texto_seguro internamente, preservando saltos de línea)
    campos_informe = [
        ("Resultados", getattr(informe, "resultados", "") or "Sin resultados registrados."),
        ("Conclusiones", getattr(informe, "conclusiones", "") or "Sin conclusiones registradas."),
        ("Recomendaciones", getattr(informe, "recomendaciones", "") or "Sin recomendaciones registradas."),
    ]

    historia.extend(construir_tabla_campos(campos_informe, estilos=estilos))

    # 4. Compilar documento en memoria (incluye pie de página y numeración)
    return construir_documento_pdf(
        historia,
        pie_texto="SISTRA · Universidad de Pamplona — Informe de Trabajo Social",
    )