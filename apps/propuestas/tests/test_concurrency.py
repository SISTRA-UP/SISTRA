import threading
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.propuestas.models import Propuesta, EstadoTramite
from apps.procesos.models import ProcesoTrabajoSocial
from apps.personas.models import Estudiante

User = get_user_model()

class ConcurrencySendTest(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        # Create a student user and related objects
        self.user = User.objects.create_user(username='student', password='testpass')
        self.client.login(username='student', password='testpass')
        # Minimal related objects required for a proposal
        self.estudiante = Estudiante.objects.create(usuario=self.user, numero_identificacion='123')
        self.proceso = ProcesoTrabajoSocial.objects.create(estudiante=self.estudiante)
        # Ensure no existing proposal
        Propuesta.objects.filter(proceso=self.proceso).delete()

    def _post_send(self):
        return self.client.post(reverse('propuestas:montaje'), {'accion': 'enviar'})

    def test_concurrent_send(self):
        # First request creates a draft proposal
        resp1 = self._post_send()
        self.assertEqual(resp1.status_code, 302)  # redirect after successful send
        # Now attempt two concurrent sends (simulate double click)
        def send():
            self.client.post(reverse('propuestas:montaje'), {'accion': 'enviar'})

        thread1 = threading.Thread(target=send)
        thread2 = threading.Thread(target=send)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # There should be exactly one proposal in EN_REVISION
        self.assertEqual(Propuesta.objects.filter(proceso=self.proceso, estado=EstadoTramite.EN_REVISION).count(), 1)
        # Exactly one historial entry and one notification
        from apps.seguimiento.models import HistorialEstado, Notificacion
        self.assertEqual(HistorialEstado.objects.filter(propuesta__proceso=self.proceso).count(), 1)
        self.assertEqual(Notificacion.objects.filter(propuesta__proceso=self.proceso).count(), 1)
