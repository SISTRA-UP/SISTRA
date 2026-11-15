"""SISTRA-06 · Registra el permiso de montaje de informes."""

from django.db import migrations


NOMBRE_PERMISO = "informe.montar"


def crear_permiso(apps, schema_editor):
    Rol = apps.get_model("usuarios", "Rol")
    Permiso = apps.get_model("usuarios", "Permiso")
    RolPermiso = apps.get_model("usuarios", "RolPermiso")

    base = schema_editor.connection.alias

    estudiante = Rol.objects.using(base).get(nombre="Estudiante")

    permiso, _ = Permiso.objects.using(base).get_or_create(
        nombre=NOMBRE_PERMISO,
        defaults={
            "descripcion": (
                "Diligenciar y enviar el informe de Trabajo Social "
                "asociado a su propuesta aprobada."
            ),
            "estado": "Activo",
        },
    )

    RolPermiso.objects.using(base).get_or_create(
        rol=estudiante,
        permiso=permiso,
    )


def quitar_permiso(apps, schema_editor):
    RolPermiso = apps.get_model("usuarios", "RolPermiso")

    base = schema_editor.connection.alias

    # Retira la asignación al Estudiante sin borrar el catálogo
    # ni modificar asignaciones que puedan tener otros roles.
    RolPermiso.objects.using(base).filter(
        rol__nombre="Estudiante",
        permiso__nombre=NOMBRE_PERMISO,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("informes", "0002_siembra_permiso_aprobacion_informe"),
        ("usuarios", "0003_siembra_permisos_de_gestion_de_usuarios"),
    ]

    operations = [
        migrations.RunPython(crear_permiso, quitar_permiso),
    ]