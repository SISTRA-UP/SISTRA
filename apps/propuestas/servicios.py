"""Compatibilidad de importación para SISTRA-03.

Permite importar `generar_pdf_propuesta` vía `apps.propuestas.servicios`
tal como espera `apps/cargue_up/views/cargue_propuesta.py`.
"""

from apps.propuestas.services.documento_pdf import (
    CAMPOS_FORMULARIO_PROPUESTA,
    construir_encabezado_pdf,
    construir_tabla_campos,
    construir_tabla_cronograma,
    generar_pdf_propuesta,
    obtener_estilos_pdf,
)

__all__ = [
    "CAMPOS_FORMULARIO_PROPUESTA",
    "construir_encabezado_pdf",
    "construir_tabla_campos",
    "construir_tabla_cronograma",
    "generar_pdf_propuesta",
    "obtener_estilos_pdf",
]
