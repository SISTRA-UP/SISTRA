"""Siembra los permisos de gestión de usuarios de SISTRA-10.

Los exigen los criterios de SIS-18 que el Product Owner añadió el 2026-11-07:
el ADMO crea usuarios, los edita y les cambia el rol, y elimina a los que no
tengan trámites. Misma convención `<entidad>.<accion>` de la migración 0002
(decisión D-08, confirmada por el BRD v1.2, nota técnica §5.11).
"""

from django.db import migrations

ROL_ADMINISTRADOR = 'Administrador'

PERMISOS_DE_GESTION_DE_USUARIOS = [
    ('usuario.crear', 'Crear un usuario y, si es Director, asignarle su carrera.'),
    ('usuario.editar', 'Cambiar los datos de un usuario y su rol.'),
    ('usuario.eliminar', 'Eliminar un usuario que no tenga trámites ni historial.'),
]


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    administrador = Rol.objects.using(base).get(nombre=ROL_ADMINISTRADOR)
    for nombre, descripcion in PERMISOS_DE_GESTION_DE_USUARIOS:
        permiso, _ = Permiso.objects.using(base).get_or_create(
            nombre=nombre, defaults={'descripcion': descripcion}
        )
        if not RolPermiso.objects.using(base).filter(
            rol=administrador, permiso=permiso
        ).exists():
            RolPermiso.objects.using(base).create(rol=administrador, permiso=permiso)


def quitar(apps, schema_editor):
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    nombres = [nombre for nombre, _ in PERMISOS_DE_GESTION_DE_USUARIOS]
    RolPermiso.objects.using(base).filter(permiso__nombre__in=nombres).delete()
    Permiso.objects.using(base).filter(nombre__in=nombres).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0002_siembra_roles_base_y_permisos'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
