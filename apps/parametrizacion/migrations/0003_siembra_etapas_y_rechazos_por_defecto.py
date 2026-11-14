from django.db import migrations


# Estados oficiales del proceso sin "Borrador", configurados como etapas generales
ETAPAS_DEFECTO = [
    {
        'orden': 1,
        'nombre': 'En revisión',
        'descripcion': 'Propuesta o informe radicado y en proceso de evaluación académica y metodológica.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 2,
        'nombre': 'Requiere modificación',
        'descripcion': 'Devuelto al estudiante con observaciones para que realice los ajustes solicitados.',
        'obligatoria': False,
        'estado': 'Activo',
    },
    {
        'orden': 3,
        'nombre': 'Aprobado',
        'descripcion': 'Aprobación académica formal en SISTRA para habilitar el cargue en Plataforma UP.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 4,
        'nombre': 'Subido en UP',
        'descripcion': 'El estudiante declara formalmente que radicó el documento aprobado en la Plataforma UP.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 5,
        'nombre': 'Aprobado en UP',
        'descripcion': 'El Director valida el soporte institucional en la Plataforma UP y concluye el trámite.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 6,
        'nombre': 'Rechazado',
        'descripcion': 'Trámite no aprobado por incumplimiento de requisitos o plazo reglamentario vencido.',
        'obligatoria': False,
        'estado': 'Activo',
    },
]

TIPOS_RECHAZO_DEFECTO = [
    {
        'nombre': 'Documentación incompleta',
        'descripcion': 'Falta de soportes, cartas de aceptación de la entidad receptora o anexos obligatorios.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Incumplimiento de requisitos de plantilla',
        'descripcion': 'El documento no se ajusta a la plantilla oficial de la Universidad o presenta problemas de formato.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Objetivos o plan de trabajo no pertinentes',
        'descripcion': 'Las actividades propuestas no corresponden al perfil profesional o a los lineamientos de Trabajo Social.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Inconsistencia en cronograma o dedicación horaria',
        'descripcion': 'Las fechas programadas o la distribución de horas no cumplen la reglamentación académica vigente.',
        'estado': 'Activo',
    },
    {
        'nombre': 'Falta de aval de la entidad receptora',
        'descripcion': 'No se adjunta constancia formal firmada por el responsable de la institución o comunidad donde se ejecuta.',
        'estado': 'Activo',
    },
]


def sembrar_estados(apps, schema_editor):
    Actividad = apps.get_model('parametrizacion', 'Actividad')
    TipoRechazo = apps.get_model('parametrizacion', 'TipoRechazo')

    for etapa in ETAPAS_DEFECTO:
        Actividad.objects.get_or_create(
            orden=etapa['orden'],
            defaults={
                'nombre': etapa['nombre'],
                'descripcion': etapa['descripcion'],
                'obligatoria': etapa['obligatoria'],
                'estado': etapa['estado'],
            },
        )

    for tipo in TIPOS_RECHAZO_DEFECTO:
        TipoRechazo.objects.get_or_create(
            nombre=tipo['nombre'],
            defaults={
                'descripcion': tipo['descripcion'],
                'estado': tipo['estado'],
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('parametrizacion', '0002_siembra_carrera_derecho'),
    ]

    operations = [
        migrations.RunPython(sembrar_estados, migrations.RunPython.noop),
    ]
