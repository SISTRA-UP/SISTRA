"""SISTRA-11 · Elimina el campo telefono del modelo Usuario.

El BRD v1.2 lo suprimió. La columna la agrega 0004_agrega_telefono;
IF EXISTS evita fallo si la columna ya fue quitada manualmente.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0008_merge_20261112_1707'),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE usuario DROP COLUMN IF EXISTS telefono',
            reverse_sql="ALTER TABLE usuario ADD COLUMN telefono VARCHAR(20) NOT NULL DEFAULT ''",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name='usuario', name='telefono'),
            ],
        ),
    ]
