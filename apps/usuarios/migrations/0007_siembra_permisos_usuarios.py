"""Siembra los permisos de gestión de usuarios para el rol Administrador.

Trae la convención `entidad.accion` de la rama develop (migración
0003_siembra_permisos_de_gestion_de_usuarios). Añadidos por el
Product Owner en SIS-18 (BRD v1.2, nota técnica §5.11):
el Administrador puede crear, editar y eliminar usuarios.
"""

from django.db import migrations

ROL_ADMINISTRADOR = 'Administrador'

PERMISOS = [
    ('usuario.crear',    'Crear un usuario y, si es Director, asignarle su carrera.'),
    ('usuario.editar',   'Cambiar los datos de un usuario y su rol.'),
    ('usuario.eliminar', 'Eliminar un usuario que no tenga trámites ni historial.'),
]


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    admin = Rol.objects.using(base).get(nombre=ROL_ADMINISTRADOR)
    for nombre, descripcion in PERMISOS:
        permiso, _ = Permiso.objects.using(base).get_or_create(
            nombre=nombre,
            defaults={'descripcion': descripcion},
        )
        if not RolPermiso.objects.using(base).filter(
            rol=admin, permiso=permiso
        ).exists():
            RolPermiso.objects.using(base).create(rol=admin, permiso=permiso)


def quitar(apps, schema_editor):
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    nombres = [n for n, _ in PERMISOS]
    RolPermiso.objects.using(base).filter(permiso__nombre__in=nombres).delete()
    Permiso.objects.using(base).filter(nombre__in=nombres).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0006_siembra_permisos_roles'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
