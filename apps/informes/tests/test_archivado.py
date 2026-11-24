"""B6b: archivado automático de informes rechazados en el comando compartido."""

import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.informes.models import Informe
from apps.parametrizacion import servicios
from apps.propuestas.models import EstadoTramite
from apps.propuestas.tests.test_aprobacion import BaseAprobacionTestCase
from apps.seguimiento.models import Auditoria, HistorialEstado


PLAZO = 'dias_archivado_informe_rechazado'
ACCION = 'ARCHIVAR_INFORME_RECHAZADO'


class TestArchivarInformes(BaseAprobacionTestCase):
    def _rechazado_hace(self, estudiante, codigo, dias, *, con_historial=True):
        propuesta = self.crear_propuesta(
            estudiante, 'PROP-' + codigo, estado=EstadoTramite.APROBADO_EN_UP,
        )
        informe = Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=self.periodo,
            codigo=codigo,
            estado=EstadoTramite.RECHAZADO,
            fecha_envio=timezone.now() - timedelta(days=dias + 4),
        )
        if con_historial:
            HistorialEstado.objects.create(
                informe=informe,
                usuario=self.user_director,
                estado_anterior=EstadoTramite.EN_REVISION,
                estado_nuevo=EstadoTramite.RECHAZADO,
                tipo_accion='decision_informe',
                fecha_hora=timezone.now() - timedelta(days=dias),
            )
        return informe

    def _ejecutar(self):
        salida = StringIO()
        call_command('archivar_rechazados', stdout=salida)
        return salida.getvalue()

    def test_archiva_31_dias_no_29_y_exige_historial(self):
        # La falta del parámetro de propuestas no debe impedir procesar informes.
        servicios.guardar(PLAZO, '30', self.user_director)
        antiguo = self._rechazado_hace(self.estudiante_1, 'INF-B6B-31', 31)
        reciente = self._rechazado_hace(self.estudiante_2, 'INF-B6B-29', 29)
        sin_historial = self._rechazado_hace(
            self.estudiante_ajeno, 'INF-B6B-SIN', 100, con_historial=False,
        )

        salida = self._ejecutar()

        antiguo.refresh_from_db()
        reciente.refresh_from_db()
        sin_historial.refresh_from_db()
        self.assertTrue(antiguo.archivado)
        self.assertIsNotNone(antiguo.fecha_archivado)
        self.assertEqual(antiguo.estado, EstadoTramite.RECHAZADO)
        self.assertFalse(reciente.archivado)
        self.assertFalse(sin_historial.archivado)
        self.assertIn('Informes archivados: 1', salida)
        registro = Auditoria.objects.get(
            tabla_afectada='informe', id_registro_afectado=antiguo.pk, accion=ACCION,
        )
        self.assertIsNone(registro.usuario)
        self.assertEqual(registro.resultado, 'Éxito')

    def test_segunda_ejecucion_no_cambia_fecha_ni_duplica_auditoria(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        informe = self._rechazado_hace(self.estudiante_1, 'INF-B6B-DOBLE', 45)

        self._ejecutar()
        informe.refresh_from_db()
        fecha = informe.fecha_archivado
        salida = self._ejecutar()

        informe.refresh_from_db()
        self.assertEqual(informe.fecha_archivado, fecha)
        self.assertIn('Informes archivados: 0', salida)
        self.assertEqual(Auditoria.objects.filter(accion=ACCION, tabla_afectada='informe').count(), 1)

    def test_sin_parametro_no_archiva_ni_audita(self):
        informe = self._rechazado_hace(self.estudiante_1, 'INF-B6B-SIN-PLAZO', 400)

        salida = self._ejecutar()

        informe.refresh_from_db()
        self.assertFalse(informe.archivado)
        self.assertIn(PLAZO, salida)
        self.assertIn('no se archivó ningún informe', salida.lower())
        self.assertFalse(Auditoria.objects.filter(accion=ACCION).exists())

    def test_reactivado_y_rechazado_recientemente_no_se_archivan(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        reactivado = self._rechazado_hace(self.estudiante_1, 'INF-B6B-REACT', 60)
        nuevo_rechazo = self._rechazado_hace(self.estudiante_2, 'INF-B6B-ULTIMO', 60)
        Informe.objects.filter(pk=reactivado.pk).update(estado=EstadoTramite.REQUIERE_MODIFICACION)
        HistorialEstado.objects.create(
            informe=nuevo_rechazo,
            usuario=self.user_director,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.RECHAZADO,
            tipo_accion='decision_informe',
            fecha_hora=timezone.now() - timedelta(days=10),
        )

        self._ejecutar()

        reactivado.refresh_from_db()
        nuevo_rechazo.refresh_from_db()
        self.assertFalse(reactivado.archivado)
        self.assertFalse(nuevo_rechazo.archivado)

    def test_informe_archivado_por_comando_no_se_puede_reactivar(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        informe = self._rechazado_hace(self.estudiante_1, 'INF-B6B-BLOQUEADO', 31)
        self._ejecutar()
        informe.refresh_from_db()
        self.client.force_login(self.user_director)

        respuesta = self.client.post(reverse('informes:reactivar', kwargs={'id_informe': informe.pk}), {
            'motivo': 'El rechazo fue un error.',
            'fecha_actualizacion': informe.fecha_actualizacion.isoformat(),
        })

        self.assertEqual(respuesta.status_code, 404)
        informe.refresh_from_db()
        self.assertTrue(informe.archivado)
        self.assertEqual(informe.estado, EstadoTramite.RECHAZADO)
        self.assertFalse(HistorialEstado.objects.filter(
            informe=informe, tipo_accion='reactivacion_informe',
        ).exists())

    def test_informe_archivado_impide_reactivar_lote_completo(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        archivado = self._rechazado_hace(self.estudiante_1, 'INF-B6B-LOTE-VIEJO', 31)
        vigente = self._rechazado_hace(self.estudiante_2, 'INF-B6B-LOTE-NUEVO', 29)
        self._ejecutar()
        archivado.refresh_from_db()
        self.client.force_login(self.user_director)

        respuesta = self.client.post(reverse('informes:reactivar_masivo'), {
            'motivo': 'Rechazos registrados por error.',
            'informes': [archivado.pk, vigente.pk],
            'versiones': json.dumps({
                str(i.pk): i.fecha_actualizacion.isoformat() for i in (archivado, vigente)
            }),
        })

        self.assertEqual(respuesta.status_code, 400)
        vigente.refresh_from_db()
        self.assertEqual(vigente.estado, EstadoTramite.RECHAZADO)
        self.assertFalse(vigente.archivado)
        self.assertFalse(HistorialEstado.objects.filter(
            informe=vigente, tipo_accion='reactivacion_masiva_informe',
        ).exists())

    def test_fallo_de_auditoria_revierte_el_archivado(self):
        servicios.guardar(PLAZO, '30', self.user_director)
        informe = self._rechazado_hace(self.estudiante_1, 'INF-B6B-AUDITORIA', 31)

        with patch(
            'apps.propuestas.management.commands.archivar_rechazados.Auditoria.objects.create',
            side_effect=RuntimeError('fallo simulado'),
        ):
            with self.assertRaises(RuntimeError):
                self._ejecutar()

        informe.refresh_from_db()
        self.assertFalse(informe.archivado)
        self.assertIsNone(informe.fecha_archivado)

    def test_rechazo_reciente_entre_consulta_y_bloqueo_no_se_archiva(self):
        """Se revalida el último rechazo después de seleccionar el informe."""
        servicios.guardar(PLAZO, '30', self.user_director)
        informe = self._rechazado_hace(self.estudiante_1, 'INF-B6B-CARRERA', 60)
        consulta_real = Informe.objects.select_for_update()

        def agregar_rechazo_reciente(*, pk):
            HistorialEstado.objects.create(
                informe_id=pk,
                usuario=self.user_director,
                estado_anterior=EstadoTramite.EN_REVISION,
                estado_nuevo=EstadoTramite.RECHAZADO,
                tipo_accion='decision_informe',
                fecha_hora=timezone.now() - timedelta(days=2),
            )
            return consulta_real.get(pk=pk)

        with patch(
            'apps.propuestas.management.commands.archivar_rechazados.Informe.objects.select_for_update'
        ) as seleccionar:
            seleccionar.return_value.get.side_effect = agregar_rechazo_reciente
            salida = self._ejecutar()

        informe.refresh_from_db()
        self.assertFalse(informe.archivado)
        self.assertIsNone(informe.fecha_archivado)
        self.assertIn('Informes archivados: 0', salida)
        self.assertFalse(Auditoria.objects.filter(accion=ACCION).exists())
