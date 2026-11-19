"""Siembra el permiso `dashboard.ver` y lo asigna a los roles base de SISTRA."""

from django.db import migrations

PERMISO_DASHBOARD = 'dashboard.ver'
ROLES_BASE = ('Estudiante', 'Director', 'Administrador')


def crear_permiso_dashboard(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Permiso = apps.get_model('usuarios', 'Permiso')
    Rol = apps.get_model('usuarios', 'Rol')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')

    permiso, _ = Permiso.objects.using(db_alias).get_or_create(
        nombre=PERMISO_DASHBOARD,
        defaults={
            'descripcion': 'Consultar el panel principal de inicio según el rol',
            'estado': 'Activo',
        },
    )

    for nombre_rol in ROLES_BASE:
        rol, _ = Rol.objects.using(db_alias).get_or_create(
            nombre=nombre_rol,
            defaults={'estado': 'Activo'},
        )
        ya_asignado = (
            RolPermiso.objects.using(db_alias)
            .filter(rol=rol, permiso=permiso)
            .exists()
        )
        if not ya_asignado:
            RolPermiso.objects.using(db_alias).create(rol=rol, permiso=permiso)


def revertir_permiso_dashboard(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')

    permiso = Permiso.objects.using(db_alias).filter(nombre=PERMISO_DASHBOARD).first()
    if permiso:
        RolPermiso.objects.using(db_alias).filter(permiso=permiso).delete()
        permiso.delete()


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('usuarios', '0001_crea_usuarios_roles_permisos'),
    ]

    operations = [
        migrations.RunPython(crear_permiso_dashboard, revertir_permiso_dashboard),
    ]