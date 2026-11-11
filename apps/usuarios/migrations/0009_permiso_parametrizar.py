from django.db import migrations, models


def crear_permiso(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')

    permiso, _ = Permiso.objects.get_or_create(
        nombre='sistema.parametrizar',
        defaults={
            'descripcion': 'Acceso a parametrización (RN-11-01, EX-03).',
            'estado': 'Activo',
        },
    )
    admin_rol, _ = Rol.objects.get_or_create(
        nombre='Administrador',
        defaults={'estado': 'Activo'},
    )
    RolPermiso.objects.get_or_create(rol=admin_rol, permiso=permiso)


def eliminar_permiso(apps, schema_editor):
    Permiso = apps.get_model('usuarios', 'Permiso')
    Permiso.objects.filter(nombre='sistema.parametrizar').delete()


class Migration(migrations.Migration):
    """Crea el permiso `sistema.parametrizar` y lo asigna al rol Administrador."""

    dependencies = [
        ('usuarios', '0008_merge_remove_telefono'),
    ]

    operations = [
        migrations.RunPython(crear_permiso, eliminar_permiso),
    ]
