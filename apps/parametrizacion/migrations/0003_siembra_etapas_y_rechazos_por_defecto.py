from django.db import migrations


ETAPAS_DEFECTO = [
    {
        'orden': 1,
        'nombre': 'Presentación de Propuesta',
        'descripcion': 'El estudiante formula y radica la propuesta inicial de Trabajo Social con el aval del tutor o docente.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 2,
        'nombre': 'Revisión y Aprobación de Propuesta',
        'descripcion': 'Evaluación académica y metodológica de la propuesta por parte del Director o evaluador asignado.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 3,
        'nombre': 'Cargue y Verificación en Plataforma UP',
        'descripcion': 'El estudiante declara la subida de la propuesta aprobada en la plataforma institucional UP y el Director verifica el soporte.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 4,
        'nombre': 'Ejecución del Trabajo Social',
        'descripcion': 'Desarrollo de las actividades planificadas en el cronograma institucional y cumplimiento de las horas reglamentarias.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 5,
        'nombre': 'Presentación de Informe Final',
        'descripcion': 'Consolidación de resultados, evidencias y entrega del informe final de cumplimiento de Trabajo Social.',
        'obligatoria': True,
        'estado': 'Activo',
    },
    {
        'orden': 6,
        'nombre': 'Aprobación y Certificación Final',
        'descripcion': 'Revisión final, visto bueno institucional en Plataforma UP y cierre exitoso del proceso de Trabajo Social.',
        'obligatoria': True,
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
