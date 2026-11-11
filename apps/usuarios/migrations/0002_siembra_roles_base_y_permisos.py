"""Siembra los roles iniciales y el catálogo de permisos de SISTRA-10.

Los roles iniciales los exige la regla de negocio §3.6 (Estudiante, Director y
Administrador, el rol que el BRD llama ADMO).

`permiso.nombre` es la cadena que las vistas comprueban con
`has_perm('...')` o `@permission_required('...')`, así que es contrato con los
demás requisitos. La convención es `<entidad>.<accion>`, en minúscula y sin
tildes. Aquí solo se siembran los permisos de SISTRA-10; cada requisito agrega
los suyos con la misma convención, en su propia migración.
"""

from django.db import migrations

ROL_ADMINISTRADOR = 'Administrador'

ROLES_INICIALES = [
    ('Estudiante', 'Estudiante que adelanta su Trabajo Social.'),
    ('Director', 'Director de una carrera: registra estudiantes y aprueba sus trámites.'),
    (ROL_ADMINISTRADOR, 'Administra roles, permisos y usuarios. Es el ADMO del BRD.'),
]

PERMISOS_DE_SISTRA_10 = [
    ('rol.ver', 'Ver la lista de roles.'),
    ('rol.crear', 'Crear un rol.'),
    ('rol.editar', 'Cambiar el nombre y la descripción de un rol.'),
    ('rol.inactivar', 'Inactivar o reactivar un rol.'),
    ('rol.asignar_permisos', 'Elegir qué permisos tiene un rol.'),
    ('usuario.ver', 'Buscar y filtrar usuarios.'),
    ('usuario.inactivar', 'Inactivar o reactivar un usuario.'),
]


def sembrar(apps, schema_editor):
    Rol = apps.get_model('usuarios', 'Rol')
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    for nombre, descripcion in ROLES_INICIALES:
        Rol.objects.using(base).get_or_create(
            nombre=nombre, defaults={'descripcion': descripcion}
        )

    administrador = Rol.objects.using(base).get(nombre=ROL_ADMINISTRADOR)
    for nombre, descripcion in PERMISOS_DE_SISTRA_10:
        permiso, _ = Permiso.objects.using(base).get_or_create(
            nombre=nombre, defaults={'descripcion': descripcion}
        )
        if not RolPermiso.objects.using(base).filter(
            rol=administrador, permiso=permiso
        ).exists():
            RolPermiso.objects.using(base).create(rol=administrador, permiso=permiso)


def quitar(apps, schema_editor):
    """Deshace la siembra de permisos.

    Los roles no se borran: `usuario.id_rol` protege el borrado (ON DELETE
    RESTRICT), así que quitarlos tumbaría a los usuarios que ya los tengan.
    """
    Permiso = apps.get_model('usuarios', 'Permiso')
    RolPermiso = apps.get_model('usuarios', 'RolPermiso')
    base = schema_editor.connection.alias

    nombres = [nombre for nombre, _ in PERMISOS_DE_SISTRA_10]
    RolPermiso.objects.using(base).filter(permiso__nombre__in=nombres).delete()
    Permiso.objects.using(base).filter(nombre__in=nombres).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0001_crea_usuarios_roles_permisos'),
    ]

    operations = [
        migrations.RunPython(sembrar, quitar),
    ]
