"""SISTRA-07 · Registra el permiso de aprobación de informes."""

from django.db import migrations


NOMBRE_PERMISO = "informe.aprobar"


def crear_permiso(apps, schema_editor):
    Rol = apps.get_model("usuarios", "Rol")
    Permiso = apps.get_model("usuarios", "Permiso")
    RolPermiso = apps.get_model("usuarios", "RolPermiso")

    base = schema_editor.connection.alias

    director = Rol.objects.using(base).get(nombre="Director")

    permiso, _ = Permiso.objects.using(base).get_or_create(
        nombre=NOMBRE_PERMISO,
        defaults={
            "descripcion": (
                "Consultar y evaluar los informes de los estudiantes "
                "de su carrera."
            ),
            "estado": "Activo",
        },
    )

    RolPermiso.objects.using(base).get_or_create(
        rol=director,
        permiso=permiso,
    )


def quitar_permiso(apps, schema_editor):
    RolPermiso = apps.get_model("usuarios", "RolPermiso")

    base = schema_editor.connection.alias

    # Retira la asignación al Director sin borrar el catálogo
    # ni modificar asignaciones que puedan tener otros roles.
    RolPermiso.objects.using(base).filter(
        rol__nombre="Director",
        permiso__nombre=NOMBRE_PERMISO,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("informes", "0001_crea_informes"),
        ("usuarios", "0003_siembra_permisos_de_gestion_de_usuarios"),
    ]

    operations = [
        migrations.RunPython(crear_permiso, quitar_permiso),
    ]