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

    # 1. Metadatos del encabezado. Las relaciones son obligatorias en el modelo,
    # por eso se accede directamente: si falta alguna, el error debe propagarse.
    codigo = informe.codigo or "Sin código"
    version = informe.version_entrega

    estudiante_carrera = informe.propuesta.proceso.estudiante_carrera
    usuario = estudiante_carrera.estudiante.usuario
    estudiante_nombre = usuario.nombre or "No asignado"
    cedula = usuario.cedula or "No asignada"
    carrera_nombre = estudiante_carrera.carrera.nombre or "No asignada"

    periodo = _obtener_nombre_periodo(informe.propuesta)
    fecha_envio = _formatear_fecha(informe.fecha_envio)
    titulo_propuesta = informe.propuesta.titulo or "Sin título"
    entidad = informe.propuesta.entidad or "Sin entidad"

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

    # 2. Encabezado: construir_encabezado_pdf aplica _texto_seguro una sola vez.
    historia.extend(
        construir_encabezado_pdf(
            titulo="UNIVERSIDAD DE PAMPLONA",
            subtitulo="INFORME DE TRABAJO SOCIAL",
            metadatos=metadatos,
            estilos=estilos,
        )
    )

    # 3. Campos del informe: construir_tabla_campos escapa una sola vez y
    # conserva los saltos de línea de Resultados, Conclusiones y Recomendaciones.
    campos_informe = [
        ("Resultados", informe.resultados or "Sin resultados registrados."),
        ("Conclusiones", informe.conclusiones or "Sin conclusiones registradas."),
        ("Recomendaciones", informe.recomendaciones or "Sin recomendaciones registradas."),
    ]

    historia.extend(construir_tabla_campos(campos_informe, estilos=estilos))

    # 4. Compilar documento en memoria (incluye pie de página y numeración).
    return construir_documento_pdf(
        historia,
        pie_texto="SISTRA · Universidad de Pamplona — Informe de Trabajo Social",
    )