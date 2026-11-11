"""Merge de las dos ramas de migraciones de usuarios.

Resuelve el conflicto "multiple leaf nodes" uniendo:
- 0007_siembra_permisos_usuarios  (rama anterior a SISTRA-11)
- 0003_siembra_permisos_de_gestion_de_usuarios  (rama develop)
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0007_siembra_permisos_usuarios'),
        ('usuarios', '0003_siembra_permisos_de_gestion_de_usuarios'),
        ('usuarios', '0004_agrega_telefono'),
    ]

    operations = []
