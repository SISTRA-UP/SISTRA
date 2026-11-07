"""Crea dos cuentas ficticias de estudiante para pruebas manuales locales.

Las contraseñas se solicitan en una entrada oculta y se guardan únicamente
como hash mediante Usuario.objects.create_user(). El comando no cambia la
contraseña ni los datos de una cuenta que ya exista.
"""

from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.personas.models import Estudiante
from apps.usuarios.models import Estado, Rol


CUENTAS_DE_PRUEBA = (
    {
        'nombre': 'Estudiante Prueba Uno',
        'correo_institucional': 'estudiante1@unipamplona.edu.co',
        'nombre_usuario': 'estudiante1',
        'cedula': '1000000001',
    },
    {
        'nombre': 'Estudiante Prueba Dos',
        'correo_institucional': 'estudiante2@unipamplona.edu.co',
        'nombre_usuario': 'estudiante2',
        'cedula': '1000000002',
    },
)


class Command(BaseCommand):
    help = 'Crea de manera idempotente las dos cuentas locales de estudiante de prueba.'

    def handle(self, *args, **options):
        Usuario = get_user_model()
        rol, _ = Rol.objects.get_or_create(
            nombre='Estudiante',
            defaults={'estado': Estado.ACTIVO},
        )
        if rol.estado != Estado.ACTIVO:
            raise CommandError('El rol Estudiante ya existe, pero no está activo. No se modificó.')

        cuentas_existentes = {}
        cuentas_nuevas = []
        for datos in CUENTAS_DE_PRUEBA:
            usuario = Usuario.objects.filter(
                correo_institucional__iexact=datos['correo_institucional']
            ).select_related('rol').first()
            cuentas_existentes[datos['correo_institucional']] = usuario
            if usuario is None:
                cuentas_nuevas.append(datos)
            elif usuario.rol_id != rol.pk or not usuario.is_active:
                raise CommandError(
                    f"La cuenta {datos['correo_institucional']} ya existe, "
                    'pero no es un estudiante activo. No se modificó.'
                )

        contrasena = None
        if cuentas_nuevas:
            try:
                contrasena = getpass('Contraseña para las cuentas nuevas (entrada oculta): ')
                confirmacion = getpass('Repite la contraseña: ')
            except (EOFError, KeyboardInterrupt) as error:
                raise CommandError('No se recibió una contraseña; no se crearon cuentas.') from error
            if not contrasena or contrasena != confirmacion:
                raise CommandError('La contraseña está vacía o las dos entradas no coinciden.')

        creadas = 0
        perfiles_creados = 0
        try:
            with transaction.atomic():
                for datos in CUENTAS_DE_PRUEBA:
                    correo = datos['correo_institucional']
                    usuario = cuentas_existentes[correo]
                    if usuario is None:
                        usuario = Usuario.objects.create_user(
                            **datos,
                            password=contrasena,
                            rol=rol,
                            estado=Estado.ACTIVO,
                            requiere_cambio_contrasena=False,
                        )
                        creadas += 1

                    _, perfil_nuevo = Estudiante.objects.get_or_create(usuario=usuario)
                    perfiles_creados += int(perfil_nuevo)
        except IntegrityError as error:
            raise CommandError(
                'No se pudieron crear las cuentas: revisa que las cédulas y nombres '
                'de usuario de prueba no estén usados por otros registros.'
            ) from error

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {creadas} cuentas nuevas y {perfiles_creados} perfiles nuevos. '
            'Las cuentas que ya existían conservaron todos sus datos y contraseñas.'
        ))
        for datos in CUENTAS_DE_PRUEBA:
            self.stdout.write(f"- {datos['correo_institucional']}")
