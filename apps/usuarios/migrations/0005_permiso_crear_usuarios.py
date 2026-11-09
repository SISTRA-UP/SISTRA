from django.db import migrations


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')

    director, _ = Rol.objects.get_or_create(nombre='Director', defaults={'estado': 'Activo'})
    permiso, _ = Permiso.objects.get_or_create(
        nombre='crear_usuarios',
        defaults={
            'descripcion': 'Crear estudiantes uno a uno y por carga masiva.',
            'estado': 'Activo',
        },
    )
    RolPermiso.objects.get_or_create(rol=director, permiso=permiso)


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0004_agrega_telefono'),
    ]

    operations = [
        migrations.RunPython(sembrar, migrations.RunPython.noop),
    ]