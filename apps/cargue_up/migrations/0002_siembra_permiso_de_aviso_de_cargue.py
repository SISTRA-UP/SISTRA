"""Siembra el permiso de avisar «Subido en UP» (SISTRA-04 y SISTRA-08).

Se lo asigna al rol **Estudiante**, que es lo que fija la Tabla 32 del BRD
v1.2: «Avisar Subido en UP (SISTRA-04, 08) → ✓ Estudiante». El nombre sigue
la convención `<entidad>.<accion>` de SISTRA-10.

Los permisos viven en `usuarios.permiso`, pero se siembran desde aquí porque
son de este requisito (misma decisión que `personas/0002` y `propuestas/0002`).
"""

from django.db import migrations

ROL_ESTUDIANTE = 'Estudiante'

PERMISOS_DE_AVISO = [
    (
        'cargue_up.avisar',
        'Avisar que la propuesta o el informe aprobado ya se subió a la Plataforma UP (Subido en UP).',
    ),
]


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    estudiante = Rol.objects.using(base).get(nombre=ROL_ESTUDIANTE)
    for nombre, descripcion in PERMISOS_DE_AVISO:
        permiso, _ = Permiso.objects.using(base).get_or_create(
            nombre=nombre, defaults={'descripcion': descripcion}
        )
        if not RolPermiso.objects.using(base).filter(
            rol=estudiante, permiso=permiso
        ).exists():
            RolPermiso.objects.using(base).create(rol=estudiante, permiso=permiso)


def quitar(apps, schema_editor):
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    nombres = [nombre for nombre, _ in PERMISOS_DE_AVISO]
    RolPermiso.objects.using(base).filter(permiso__nombre__in=nombres).delete()
    Permiso.objects.using(base).filter(nombre__in=nombres).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cargue_up', '0001_crea_cargues_up'),
        # El rol Estudiante lo siembra la 0002 de usuarios y la 0003 completa
        # el catálogo: esta migración tiene que correr después de las dos.
        ('usuarios', '0003_siembra_permisos_de_gestion_de_usuarios'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]