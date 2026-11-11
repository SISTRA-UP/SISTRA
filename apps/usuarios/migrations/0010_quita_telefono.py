"""Elimina el campo `telefono` de la tabla `usuario`.

Usa IF EXISTS para ser idempotente:
- En bases nuevas (test DB): la columna existe tras 0004_agrega_telefono y se borra aquí.
- En bases existentes donde ya fue quitada manualmente: no falla.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0009_permiso_parametrizar'),
    ]

    operations = [
        # RunSQL con IF EXISTS para manejar ambos casos:
        # 1. Instalación nueva (test DB): la columna existe, se elimina.
        # 2. BD existente donde fue quitada antes: no falla.
        migrations.RunSQL(
            sql='ALTER TABLE usuario DROP COLUMN IF EXISTS telefono;',
            reverse_sql='ALTER TABLE usuario ADD COLUMN telefono VARCHAR(20) NOT NULL DEFAULT \'\';',
        ),
        # Actualiza el estado interno de Django para que sepa que el campo ya no existe.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name='usuario',
                    name='telefono',
                ),
            ],
        ),
    ]
