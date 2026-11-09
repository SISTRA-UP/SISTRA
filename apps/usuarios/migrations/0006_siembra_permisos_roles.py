"""Siembra los permisos de gestión de roles para el rol Administrador.

Trae la convención `entidad.accion` de la rama develop (migración
0002_siembra_roles_base_y_permisos) que no existía en esta rama.
Los usa SISTRA-10 para controlar quién puede ver, crear, editar e
inactivar roles, y quién puede asignarles permisos.
"""

from django.db import migrations

ROL_ADMINISTRADOR = 'Administrador'

PERMISOS = [
    ('rol.ver',              'Ver la lista de roles.'),
    ('rol.crear',            'Crear un rol.'),
    ('rol.editar',           'Cambiar el nombre y la descripción de un rol.'),
    ('rol.inactivar',        'Inactivar o reactivar un rol.'),
    ('rol.asignar_permisos', 'Elegir qué permisos tiene un rol.'),
    ('usuario.ver',          'Buscar y filtrar usuarios.'),
    ('usuario.inactivar',    'Inactivar o reactivar un usuario.'),
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
        ('usuarios', '0005_permiso_crear_usuarios'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
