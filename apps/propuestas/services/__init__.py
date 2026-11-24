"""Servicios de la app propuestas."""

from .documento_pdf import (
    CAMPOS_FORMULARIO_PROPUESTA,
    construir_encabezado_pdf,
    construir_tabla_campos,
    construir_tabla_cronograma,
    generar_pdf_propuesta,
    obtener_estilos_pdf,
)
from .montaje import (
    CAMPOS_PLANTILLA_REQUERIDOS,
    ETIQUETAS_CAMPOS,
    PlantillaInvalidaError,
    extraer_datos_plantilla,
    normalizar_etiqueta,
)

__all__ = [
    "CAMPOS_FORMULARIO_PROPUESTA",
    "CAMPOS_PLANTILLA_REQUERIDOS",
    "ETIQUETAS_CAMPOS",
    "PlantillaInvalidaError",
    "construir_encabezado_pdf",
    "construir_tabla_campos",
    "construir_tabla_cronograma",
    "extraer_datos_plantilla",
    "generar_pdf_propuesta",
    "normalizar_etiqueta",
    "obtener_estilos_pdf",
]
