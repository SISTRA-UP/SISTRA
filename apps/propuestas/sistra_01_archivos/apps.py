from django.apps import AppConfig


class PropuestasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "propuestas"

    def ready(self):
        from . import signals  # noqa: F401  (registra los receptores)
