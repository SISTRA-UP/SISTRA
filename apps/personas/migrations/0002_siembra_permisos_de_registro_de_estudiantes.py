"""Siembra los permisos del registro de estudiantes (SISTRA-10, subtarea SIS-19).

Se los asigna al rol **Director**, que es lo que fija la Tabla 32 del BRD v1.2:
«Registrar estudiantes (SISTRA-10) → ✓ Director». Misma convención
`<entidad>.<accion>` de las migraciones 0002 y 0003 de `usuarios` (decisión
D-08, confirmada por la nota técnica del BRD §5.11).

Los permisos viven en `usuarios.permiso`, pero se siembran desde aquí porque son
de este frente del requisito (decisión D-13).
"""

from django.db import migrations

ROL_DIRECTOR = 'Director'

PERMISOS_DEL_REGISTRO = [
    ('estudiante.registrar', 'Registrar estudiantes uno a uno en su carrera.'),
    ('estudiante.cargar_csv', 'Registrar estudiantes cargando un archivo CSV.'),
]


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    director = Rol.objects.using(base).get(nombre=ROL_DIRECTOR)
    for nombre, descripcion in PERMISOS_DEL_REGISTRO:
        permiso, _ = Permiso.objects.using(base).get_or_create(
            nombre=nombre, defaults={'descripcion': descripcion}
        )
        if not RolPermiso.objects.using(base).filter(
            rol=director, permiso=permiso
        ).exists():
            RolPermiso.objects.using(base).create(rol=director, permiso=permiso)


def quitar(apps, schema_editor):
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    nombres = [nombre for nombre, _ in PERMISOS_DEL_REGISTRO]
    RolPermiso.objects.using(base).filter(permiso__nombre__in=nombres).delete()
    Permiso.objects.using(base).filter(nombre__in=nombres).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('personas', '0001_crea_estudiantes_y_directores'),
        # El rol Director lo siembra la 0002 de usuarios, y la 0003 completa el
        # catálogo: esta migración tiene que correr después de las dos.
        ('usuarios', '0003_siembra_permisos_de_gestion_de_usuarios'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
