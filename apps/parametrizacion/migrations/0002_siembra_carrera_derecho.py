from django.db import migrations

CODIGO_SNIES_DERECHO = '52382'


def sembrar(apps, schema_editor):
    Facultad = apps.get_model('parametrizacion', 'Facultad')
    Carrera = apps.get_model('parametrizacion', 'Carrera')

    campos = {f.name for f in Facultad._meta.get_fields()}
    defaults = {'estado': 'Activo'} if 'estado' in campos else {}
    facultad, _ = Facultad.objects.get_or_create(
        nombre='Artes y Humanidades', defaults=defaults
    )
    Carrera.objects.get_or_create(
        codigo=CODIGO_SNIES_DERECHO,
        defaults={'nombre': 'Derecho', 'facultad': facultad, 'estado': 'Activo'},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('parametrizacion', '0001_crea_catalogos_y_configuracion'),
    ]

    operations = [
        migrations.RunPython(sembrar, migrations.RunPython.noop),
    ]