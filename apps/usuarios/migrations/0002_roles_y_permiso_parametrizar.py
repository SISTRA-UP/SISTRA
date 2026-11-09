from django.db import migrations


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')

    for nombre, descripcion in (
        ('Estudiante', 'Estudiante que realiza el trabajo social.'),
        ('Director', 'Director que revisa y aprueba los trámites.'),
    ):
        Rol.objects.get_or_create(
            nombre=nombre, defaults={'descripcion': descripcion, 'estado': 'Activo'}
        )

    administrador, _ = Rol.objects.get_or_create(
        nombre='Administrador', defaults={'estado': 'Activo'}
    )
    permiso, _ = Permiso.objects.get_or_create(
        nombre='parametrizar_sistema',
        defaults={
            'descripcion': 'Acceder al módulo de Parametrización (SISTRA-11).',
            'estado': 'Activo',
        },
    )
    RolPermiso.objects.get_or_create(rol=administrador, permiso=permiso)


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0001_crea_usuarios_roles_permisos'),
    ]

    operations = [
        migrations.RunPython(sembrar, migrations.RunPython.noop),
    ]