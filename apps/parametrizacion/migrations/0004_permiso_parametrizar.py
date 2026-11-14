"""SISTRA-11 · Crea el permiso `sistema.parametrizar` y lo asigna al Administrador.

Sigue la convención entidad.accion usada en SISTRA-10 y SISTRA-02.
Depende de usuarios/0003 (donde ya existen Rol, Permiso y RolPermiso) y de
parametrizacion/0003 (última migración de este módulo), tal como hizo
propuestas/0002 con su propio permiso.
"""
from django.db import migrations


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')

    admin_rol, _ = Rol.objects.get_or_create(
        nombre='Administrador',
        defaults={'estado': 'Activo'},
    )
    permiso, _ = Permiso.objects.get_or_create(
        nombre='sistema.parametrizar',
        defaults={
            'descripcion': 'Acceder al módulo de Parametrización (SISTRA-11).',
            'estado': 'Activo',
        },
    )
    RolPermiso.objects.get_or_create(rol=admin_rol, permiso=permiso)


def quitar(apps, schema_editor):
    Permiso = apps.get_model('usuarios', 'Permiso')
    Permiso.objects.filter(nombre='sistema.parametrizar').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('parametrizacion', '0003_siembra_etapas_y_rechazos_por_defecto'),
        ('usuarios', '0003_siembra_permisos_de_gestion_de_usuarios'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
