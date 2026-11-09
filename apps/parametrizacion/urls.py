from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .views import alertas, parametrizacion, periodos

app_name = 'parametrizacion'

urlpatterns = [
    # SISTRA-11 · Parametrización
    path('', parametrizacion.InicioView.as_view(), name='parametrizacion'),
    path('periodos/', periodos.PeriodosView.as_view(), name='periodos'),
    path('periodos/nuevo/', periodos.PeriodoFormView.as_view(), name='periodo_nuevo'),
    path('periodos/<int:pk>/editar/', periodos.PeriodoFormView.as_view(), name='periodo_editar'),
    path('alertas/', alertas.AlertasView.as_view(), name='alertas'),
    path('usuarios/', parametrizacion.UsuariosView.as_view(), name='usuarios'),
    path('usuarios/plantilla-csv/', parametrizacion.PlantillaCsvView.as_view(), name='usuarios_plantilla'),
    path('usuarios/carga-masiva/', parametrizacion.CargaMasivaView.as_view(), name='usuarios_carga'),
    path('usuarios/carga-masiva/<int:pk>/log/', parametrizacion.LogCargaView.as_view(), name='usuarios_carga_log'),
    path('directores/', parametrizacion.DirectoresView.as_view(), name='directores'),
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