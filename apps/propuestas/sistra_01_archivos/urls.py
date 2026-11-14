from django.urls import path

from .views import PropuestaTrabajoSocialView

app_name = "propuestas"

urlpatterns = [
    path("trabajo-social/propuesta/", PropuestaTrabajoSocialView.as_view(), name="propuesta_trabajo_social"),
]
