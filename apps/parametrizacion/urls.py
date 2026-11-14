from django.conf import settings
from django.urls import path

from .views import alertas, documentos, estados, parametrizacion, periodos

app_name = 'parametrizacion'

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Acceso rápido dev — solo DEBUG=True, NO commitear este bloque       #
    # Ir a /parametrizacion/dev/ para elegir rol y entrar sin contraseña  #
    # ------------------------------------------------------------------ #
    *([path('dev/', __import__('apps.parametrizacion.views.acceso_dev',
            fromlist=['AccesoDevView']).AccesoDevView.as_view(), name='acceso_dev')]
      if settings.DEBUG else []),
    # Inicio del módulo
    path('', parametrizacion.InicioView.as_view(), name='parametrizacion'),
    # Periodos
    path('periodos/', periodos.PeriodosView.as_view(), name='periodos'),
    path('periodos/nuevo/', periodos.PeriodoFormView.as_view(), name='periodo_nuevo'),
    path('periodos/<int:pk>/editar/', periodos.PeriodoFormView.as_view(), name='periodo_editar'),
    # Alertas
    path('alertas/', alertas.AlertasView.as_view(), name='alertas'),
    # Estados del proceso
    path('estados/', estados.EstadosView.as_view(), name='estados'),
    path('estados/actividades/nueva/', estados.CrearActividadView.as_view(), name='actividad_nueva'),
    path('estados/actividades/<int:pk>/editar/', estados.EditarActividadView.as_view(), name='actividad_editar'),
    path('estados/actividades/<int:pk>/eliminar/', estados.EliminarActividadView.as_view(), name='actividad_eliminar'),
    path('estados/rechazos/nuevo/', estados.CrearTipoRechazoView.as_view(), name='rechazo_nuevo'),
    path('estados/rechazos/<int:pk>/editar/', estados.EditarTipoRechazoView.as_view(), name='rechazo_editar'),
    path('estados/rechazos/<int:pk>/eliminar/', estados.EliminarTipoRechazoView.as_view(), name='rechazo_eliminar'),
    # Documentos y formatos
    path('documentos/', documentos.DocumentosView.as_view(), name='documentos'),
    path('documentos/nueva/', documentos.CrearPlantillaView.as_view(), name='documentos_nueva'),
    path('documentos/csv-estudiantes/', documentos.DescargaPlantillaCsvEstudiantesView.as_view(), name='plantilla_csv_estudiantes'),
    path('documentos/propuesta-estudiante/', documentos.DescargaPlantillaPropuestaEstudianteView.as_view(), name='plantilla_propuesta_estudiante'),
    path('documentos/<int:pk>/editar/', documentos.EditarPlantillaView.as_view(), name='documentos_editar'),
    path('documentos/<int:pk>/version/', documentos.SubirVersionView.as_view(), name='documentos_version'),
    path('documentos/<int:pk>/descargar/', documentos.DescargaPlantillaView.as_view(), name='documentos_descargar'),
]
