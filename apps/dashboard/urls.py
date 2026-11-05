"""Rutas de la app dashboard.

Agrega tus rutas debajo del comentario de tu requisito, por ejemplo:

    path('...', dashboard.inicio, name='dashboard'),

En las plantillas se enlazan con el nombre de la app:
{% url 'dashboard:dashboard' %}.
"""

from django.urls import path  # noqa: F401

from .views import dashboard  # noqa: F401  SISTRA-14

app_name = 'dashboard'

urlpatterns = [
    # SISTRA-14 · Dashboard
]
