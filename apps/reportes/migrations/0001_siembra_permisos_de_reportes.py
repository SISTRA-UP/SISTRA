"""SISTRA-12 · Registra los permisos de descarga de reportes de Trabajo Social."""

from django.db import migrations


PERMISOS = [
    (
        "reporte.descargar",
        "Descargar reportes de Trabajo Social de su carrera.",
        ["Director", "Administrador"],
    ),
    (
        "reporte.descargar_todas",
        "Descargar reportes de Trabajo Social de todas las carreras.",
        ["Administrador"],
    ),
]


def crear_permisos(apps, schema_editor):
    Rol = apps.get_model("usuarios", "Rol")
    Permiso = apps.get_model("usuarios", "Permiso")
    RolPermiso = apps.get_model("usuarios", "RolPermiso")

    base = schema_editor.connection.alias

    for nombre_permiso, descripcion, roles in PERMISOS:
        permiso, _ = Permiso.objects.using(base).get_or_create(
            nombre=nombre_permiso,
            defaults={
                "descripcion": descripcion,
                "estado": "Activo",
            },
        )
        for nombre_rol in roles:
            rol = Rol.objects.using(base).get(nombre=nombre_rol)
            RolPermiso.objects.using(base).get_or_create(
                rol=rol,
                permiso=permiso,
            )


def quitar_permisos(apps, schema_editor):
    RolPermiso = apps.get_model("usuarios", "RolPermiso")

    base = schema_editor.connection.alias

    for nombre_permiso, _, roles in PERMISOS:
        for nombre_rol in roles:
            RolPermiso.objects.using(base).filter(
                rol__nombre=nombre_rol,
                permiso__nombre=nombre_permiso,
            ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0003_siembra_permisos_de_gestion_de_usuarios"),
    ]

    operations = [
        migrations.RunPython(crear_permisos, quitar_permisos),
    ]