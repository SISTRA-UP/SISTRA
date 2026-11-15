from django.db.models import Count, Q
from apps.propuestas.models import Propuesta  # Ajusta según tus modelos reales

def obtener_datos_reporte_trabajo_social(user, date_start=None, date_end=None):
    queryset = Propuesta.objects.all()

    # Director solo ve su carrera, ADMO ve todo
    if hasattr(user, 'perfil') and user.perfil.rol == 'DIRECTOR':
        queryset = queryset.filter(carrera=user.perfil.carrera)

    if date_start:
        queryset = queryset.filter(fecha_creacion__gte=date_start)
    if date_end:
        queryset = queryset.filter(fecha_creacion__lte=date_end)

    resumen = queryset.aggregate(
        total_estudiantes=Count('estudiante', distinct=True),
        entidades_publicas=Count('entidad', filter=Q(entidad__tipo='PUBLICA'), distinct=True),
        entidades_privadas=Count('entidad', filter=Q(entidad__tipo='PRIVADA'), distinct=True)
    )

    return {
        'resumen': resumen,
        'detalle': queryset
    }