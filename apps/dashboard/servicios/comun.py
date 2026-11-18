"""Constantes y utilidades compartidas por los servicios del dashboard."""

from django.urls import reverse

RUTAS_DASHBOARD = {
    'Director': 'dashboard:docente',
    'Estudiante': 'dashboard:estudiante',
    'Administrador': 'dashboard:admo',
}

BADGES = {
    'En revisión': 'warning',
    'Aprobado': 'success',
    'Requiere modificación': 'info',
    'Rechazado': 'danger',
    'Pendiente': 'secondary',
    'En curso': 'primary',
    'Finalizada': 'success',
}


def ruta_dashboard(nombre_rol: str) -> str:
    """Devuelve la URL del dashboard asignado a un rol conocido."""
    try:
        nombre_ruta = RUTAS_DASHBOARD[nombre_rol]
    except KeyError as error:
        raise ValueError(f'No existe dashboard para el rol {nombre_rol!r}.') from error
    return reverse(nombre_ruta)
