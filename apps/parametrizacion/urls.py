from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .views import alertas, documentos, estados, parametrizacion, periodos

app_name = 'parametrizacion'

urlpatterns = [
    # SISTRA-11 · Parametrización
    path('', parametrizacion.InicioView.as_view(), name='parametrizacion'),
    path('periodos/', periodos.PeriodosView.as_view(), name='periodos'),
    path('periodos/nuevo/', periodos.PeriodoFormView.as_view(), name='periodo_nuevo'),
    path('periodos/<int:pk>/editar/', periodos.PeriodoFormView.as_view(), name='periodo_editar'),
    path('alertas/', alertas.AlertasView.as_view(), name='alertas'),
    path('estados/', estados.EstadosView.as_view(), name='estados'),
    path('estados/actividades/nueva/', estados.CrearActividadView.as_view(), name='actividad_nueva'),
    path('estados/actividades/<int:pk>/editar/', estados.EditarActividadView.as_view(), name='actividad_editar'),
    path('estados/actividades/<int:pk>/eliminar/', estados.EliminarActividadView.as_view(), name='actividad_eliminar'),
    path('estados/rechazos/nuevo/', estados.CrearTipoRechazoView.as_view(), name='rechazo_nuevo'),
    path('estados/rechazos/<int:pk>/editar/', estados.EditarTipoRechazoView.as_view(), name='rechazo_editar'),
    path('estados/rechazos/<int:pk>/eliminar/', estados.EliminarTipoRechazoView.as_view(), name='rechazo_eliminar'),
    path('usuarios/', parametrizacion.UsuariosView.as_view(), name='usuarios'),
    path('usuarios/plantilla-csv/', parametrizacion.PlantillaCsvView.as_view(), name='usuarios_plantilla'),
    path('usuarios/carga-masiva/', parametrizacion.CargaMasivaView.as_view(), name='usuarios_carga'),
    path('usuarios/carga-masiva/<int:pk>/log/', parametrizacion.LogCargaView.as_view(), name='usuarios_carga_log'),
    path('directores/', parametrizacion.DirectoresView.as_view(), name='directores'),
    # SISTRA-11 · Documentos y formatos
    path('documentos/', documentos.DocumentosView.as_view(), name='documentos'),
    path('documentos/nueva/', documentos.CrearPlantillaView.as_view(), name='documentos_nueva'),
    path('documentos/<int:pk>/editar/', documentos.EditarPlantillaView.as_view(), name='documentos_editar'),
    path('documentos/<int:pk>/version/', documentos.SubirVersionView.as_view(), name='documentos_version'),
    path('salir/', LogoutView.as_view(next_page=settings.LOGIN_URL), name='salir'),
]

if settings.LOGIN_URL == 'parametrizacion:acceso_dev':
    # Temporal: el login de SISTRA-13 solo admite estudiantes. Se elimina cuando
    # exista el acceso de Director y Administrador.
    urlpatterns += [
        path(
            'acceso-dev/',
            LoginView.as_view(
                template_name='parametrizacion/parametrizacion/acceso_dev.html',
                redirect_authenticated_user=True,
            ),
            name='acceso_dev',
        ),
    ]