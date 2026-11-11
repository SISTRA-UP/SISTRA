"""SISTRA-11 · Elimina el campo telefono del modelo Usuario.

El BRD v1.2 lo suprimió. La columna la agrega la migración 0004_agrega_telefono
(de otra rama); aquí la quitamos. IF EXISTS evita fallo si ya se aplicó manual.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0007_siembra_permisos_usuarios'),
        ('usuarios', '0003_siembra_permisos_de_gestion_de_usuarios'),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE usuario DROP COLUMN IF EXISTS telefono',
            reverse_sql='ALTER TABLE usuario ADD COLUMN telefono VARCHAR(20) NOT NULL DEFAULT \'\'',
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name='usuario', name='telefono'),
            ],
        ),
    ]
