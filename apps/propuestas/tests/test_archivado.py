"""SIS-52 · B6a: archivado automático de propuestas rechazadas (RG-13).

Una propuesta Rechazada que nadie reactiva se archiva sola cuando pasan los días que
define el ADMO en Parametrización (`dias_archivado_propuesta_rechazada`). Archivar no borra.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from apps.parametrizacion import servicios
from apps.parametrizacion.models import Parametro
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.propuestas.tests.test_aprobacion import BaseAprobacionTestCase
from apps.seguimiento.models import Auditoria, HistorialEstado

PLAZO = 'dias_archivado_propuesta_rechazada'


class TestArchivarRechazados(BaseAprobacionTestCase):

    def _rechazada_hace(self, estudiante, codigo: str, dias: int) -> Propuesta:
        """Propuesta Rechazada cuyo rechazo quedó en el historial hace `dias` días."""
        prop = self.crear_propuesta(estudiante, codigo, estado=EstadoTramite.RECHAZADO)
        HistorialEstado.objects.create(
            propuesta=prop,
            usuario=self.user_director,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.RECHAZADO,
            tipo_accion='Rechazo',
            observacion='Rechazo de prueba.',
            fecha_hora=timezone.now() - timedelta(days=dias),
        )
        return prop

    def _archivar(self) -> str:
        salida = StringIO()
        call_command('archivar_rechazados', stdout=salida)
        return salida.getvalue()

    def test_con_plazo_30_archiva_la_de_31_dias_y_no_la_de_29(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        vieja = self._rechazada_hace(self.estudiante_1, 'PROP-ARCH-31', dias=31)
        reciente = self._rechazada_hace(self.estudiante_2, 'PROP-ARCH-29', dias=29)

        self._archivar()

        vieja.refresh_from_db()
        reciente.refresh_from_db()
        self.assertTrue(vieja.archivada)
        self.assertIsNotNone(vieja.fecha_archivado)
        self.assertEqual(vieja.estado, EstadoTramite.RECHAZADO, 'Archivar no cambia el estado ni borra.')
        self.assertFalse(reciente.archivada)
        fila = Auditoria.objects.get(id_registro_afectado=vieja.pk, accion='ARCHIVAR_PROPUESTA_RECHAZADA')
        self.assertIsNone(fila.usuario)
        self.assertEqual(fila.resultado, 'Éxito')

    def test_correrlo_dos_veces_no_cambia_nada_la_segunda(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        prop = self._rechazada_hace(self.estudiante_1, 'PROP-ARCH-DOBLE', dias=45)

        self._archivar()
        prop.refresh_from_db()
        fecha_primera = prop.fecha_archivado
        self._archivar()

        prop.refresh_from_db()
        self.assertEqual(prop.fecha_archivado, fecha_primera)
        self.assertEqual(
            Auditoria.objects.filter(id_registro_afectado=prop.pk, accion='ARCHIVAR_PROPUESTA_RECHAZADA').count(), 1
        )

    def test_sin_parametro_no_archiva_y_lo_dice(self):
        Parametro.objects.filter(clave=PLAZO).delete()
        prop = self._rechazada_hace(self.estudiante_1, 'PROP-ARCH-SIN-PLAZO', dias=400)

        salida = self._archivar()

        prop.refresh_from_db()
        self.assertFalse(prop.archivada)
        self.assertIn('no hay plazo configurado', salida.lower())

    def test_reactivada_antes_del_plazo_no_se_archiva(self):
        """Si se reactivó, deja de estar en Rechazado y no se archiva aunque el rechazo sea viejo."""
        servicios.guardar(PLAZO, '30', self.user_director)
        prop = self._rechazada_hace(self.estudiante_1, 'PROP-ARCH-REACT', dias=40)
        Propuesta.objects.filter(pk=prop.pk).update(estado=EstadoTramite.EN_REVISION)

        self._archivar()

        prop.refresh_from_db()
        self.assertFalse(prop.archivada)

    def test_cuenta_desde_el_ultimo_rechazo(self):
        """Rechazada hace 60 días, reactivada y rechazada otra vez hace 10: aún no se archiva."""
        servicios.guardar(PLAZO, '30', self.user_director)
        prop = self._rechazada_hace(self.estudiante_1, 'PROP-ARCH-ULTIMO', dias=60)
        HistorialEstado.objects.create(
            propuesta=prop,
            usuario=self.user_director,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.RECHAZADO,
            tipo_accion='Rechazo',
            observacion='Segundo rechazo.',
            fecha_hora=timezone.now() - timedelta(days=10),
        )

        self._archivar()

        prop.refresh_from_db()
        self.assertFalse(prop.archivada)

    def test_si_falla_la_auditoria_no_queda_archivada_sin_registro(self):
        """El archivado y su auditoría van juntos: si la auditoría falla, no se archiva."""
        from unittest import mock

        servicios.guardar(PLAZO, '30', self.user_director)
        prop = self._rechazada_hace(self.estudiante_1, 'PROP-AUD', 31)
        with mock.patch(
            'apps.propuestas.management.commands.archivar_rechazados._auditar',
            side_effect=RuntimeError('falla la auditoría'),
        ):
            with self.assertRaises(RuntimeError):
                self._archivar()
        prop.refresh_from_db()
        self.assertFalse(prop.archivada)
        self.assertIsNone(prop.fecha_archivado)
