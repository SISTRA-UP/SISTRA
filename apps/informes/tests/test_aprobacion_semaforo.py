"""SISTRA-07 · Pruebas de los colores del semáforo."""

from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from apps.informes.views.aprobacion_semaforo import (
    calcular_semaforo_informe,
)
from apps.propuestas.models import EstadoTramite


class SemaforoInformeTests(SimpleTestCase):

    def setUp(self):
        self.ahora = timezone.now()

    def crear_informe(self, dias=0, estado=EstadoTramite.EN_REVISION):
        return SimpleNamespace(
            estado=estado,
            fecha_envio=self.ahora - timedelta(days=dias),
        )

    def test_colores_en_los_limites(self):
        casos = [
            (0, "verde"),
            (7, "verde"),
            (8, "amarillo"),
            (14, "amarillo"),
            (15, "rojo"),
            (30, "rojo"),
        ]

        for dias, color in casos:
            with self.subTest(dias=dias):
                resultado = calcular_semaforo_informe(
                    self.crear_informe(dias=dias),
                    limites=(7, 14),
                    ahora=self.ahora,
                )

                self.assertEqual(resultado["color"], color)
                self.assertEqual(resultado["dias"], dias)

    def test_no_redondea_hacia_arriba_los_dias(self):
        informe = self.crear_informe(dias=7)
        informe.fecha_envio -= timedelta(hours=23)

        resultado = calcular_semaforo_informe(
            informe,
            limites=(7, 14),
            ahora=self.ahora,
        )

        self.assertEqual(resultado["dias"], 7)
        self.assertEqual(resultado["color"], "verde")

    def test_fuera_de_revision_el_semaforo_se_detiene(self):
        for estado in EstadoTramite.values:
            if estado == EstadoTramite.EN_REVISION:
                continue

            with self.subTest(estado=estado):
                resultado = calcular_semaforo_informe(
                    self.crear_informe(dias=20, estado=estado),
                    limites=(7, 14),
                    ahora=self.ahora,
                )

                self.assertEqual(resultado["color"], "detenido")
                self.assertIsNone(resultado["dias"])

    def test_informe_sin_fecha_no_recibe_color_de_plazo(self):
        informe = self.crear_informe()
        informe.fecha_envio = None

        resultado = calcular_semaforo_informe(
            informe,
            limites=(7, 14),
            ahora=self.ahora,
        )

        self.assertEqual(resultado["color"], "sin_fecha")
        self.assertIsNone(resultado["dias"])

    def test_respeta_umbrales_personalizados(self):
        resultado = calcular_semaforo_informe(
            self.crear_informe(dias=4),
            limites=(3, 6),
            ahora=self.ahora,
        )

        self.assertEqual(resultado["color"], "amarillo")

    def test_umbrales_invalidos_usan_valores_base(self):
        resultado = calcular_semaforo_informe(
            self.crear_informe(dias=8),
            limites=(14, 7),
            ahora=self.ahora,
        )

        self.assertEqual(resultado["color"], "amarillo")
    def test_reactivacion_conserva_dias_y_excluye_tiempo_rechazado(self):
        # Base efectiva: 10 días conservados + 2 desde la reactivación.
        informe = self.crear_informe(dias=12)

        historial = [
            SimpleNamespace(
                fecha_hora=self.ahora - timedelta(days=10),
                estado_anterior=EstadoTramite.EN_REVISION,
                estado_nuevo=EstadoTramite.RECHAZADO,
            ),
            SimpleNamespace(
                fecha_hora=self.ahora - timedelta(days=2),
                estado_anterior=EstadoTramite.RECHAZADO,
                estado_nuevo=EstadoTramite.EN_REVISION,
            ),
        ]

        resultado = calcular_semaforo_informe(
            informe,
            limites=(7, 14),
            ahora=self.ahora,
            historial=historial,
        )

        # 10 días antes del rechazo + 2 después de reactivar.
        self.assertEqual(resultado["dias"], 12)
        self.assertEqual(resultado["color"], "amarillo")

    def test_informe_rechazado_conserva_tiempo_sin_seguir_contando(self):
        informe = self.crear_informe(
            dias=20,
            estado=EstadoTramite.RECHAZADO,
        )

        historial = [
            SimpleNamespace(
                fecha_hora=self.ahora - timedelta(days=10),
                estado_anterior=EstadoTramite.EN_REVISION,
                estado_nuevo=EstadoTramite.RECHAZADO,
            ),
        ]

        resultado = calcular_semaforo_informe(
            informe,
            limites=(7, 14),
            ahora=self.ahora,
            historial=historial,
        )

        self.assertEqual(resultado["color"], "detenido")
        self.assertEqual(resultado["dias_acumulados"], 10)

    def test_suma_horas_antes_de_calcular_dias_completos(self):
        informe = self.crear_informe()
        informe.fecha_envio = self.ahora - timedelta(hours=26)

        historial = [
            SimpleNamespace(
                fecha_hora=self.ahora - timedelta(hours=37),
                estado_anterior=EstadoTramite.EN_REVISION,
                estado_nuevo=EstadoTramite.RECHAZADO,
            ),
            SimpleNamespace(
                fecha_hora=self.ahora - timedelta(hours=13),
                estado_anterior=EstadoTramite.RECHAZADO,
                estado_nuevo=EstadoTramite.EN_REVISION,
            ),
        ]

        resultado = calcular_semaforo_informe(
            informe,
            limites=(7, 14),
            ahora=self.ahora,
            historial=historial,
        )

        # 13 horas + 13 horas = 26 horas: un día completo.
        self.assertEqual(resultado["dias"], 1)
        self.assertEqual(resultado["color"], "verde")

    def evento(self, dias, anterior, nuevo):
        return SimpleNamespace(
            fecha_hora=self.ahora - timedelta(days=dias),
            estado_anterior=anterior,
            estado_nuevo=nuevo,
        )

    def test_reenvio_tras_modificacion_reinicia_en_cero(self):
        # 10 días en revisión + 5 corrigiendo. SISTRA-06 reenvía ahora.
        historial = [
            self.evento(15, EstadoTramite.BORRADOR, EstadoTramite.EN_REVISION),
            self.evento(5, EstadoTramite.EN_REVISION, EstadoTramite.REQUIERE_MODIFICACION),
            self.evento(0, EstadoTramite.REQUIERE_MODIFICACION, EstadoTramite.EN_REVISION),
        ]
        resultado = calcular_semaforo_informe(
            self.crear_informe(), limites=(7, 14),
            ahora=self.ahora, historial=historial,
        )
        self.assertEqual(resultado['dias'], 0)
        self.assertEqual(resultado['color'], 'verde')

    def test_reenvio_cuenta_solo_desde_la_nueva_fecha(self):
        historial = [
            self.evento(25, EstadoTramite.BORRADOR, EstadoTramite.EN_REVISION),
            self.evento(15, EstadoTramite.EN_REVISION, EstadoTramite.REQUIERE_MODIFICACION),
            self.evento(8, EstadoTramite.REQUIERE_MODIFICACION, EstadoTramite.EN_REVISION),
        ]
        resultado = calcular_semaforo_informe(
            self.crear_informe(dias=8), limites=(7, 14),
            ahora=self.ahora, historial=historial,
        )
        self.assertEqual(resultado['dias'], 8)
        self.assertEqual(resultado['color'], 'amarillo')

    def test_reenvio_reinicia_aunque_falte_evento_en_historial(self):
        resultado = calcular_semaforo_informe(
            self.crear_informe(), limites=(7, 14), ahora=self.ahora,
            historial=[self.evento(5, EstadoTramite.EN_REVISION,
                                   EstadoTramite.REQUIERE_MODIFICACION)],
        )
        self.assertEqual(resultado['dias'], 0)

    def test_decision_del_nuevo_envio_no_suma_ciclos_anteriores(self):
        informe = self.crear_informe(dias=4, estado=EstadoTramite.RECHAZADO)
        informe.fecha_actualizacion = self.ahora  # Edición posterior.
        resultado = calcular_semaforo_informe(
            informe, limites=(7, 14), ahora=self.ahora,
            historial=[
                self.evento(20, EstadoTramite.BORRADOR, EstadoTramite.EN_REVISION),
                self.evento(10, EstadoTramite.EN_REVISION, EstadoTramite.REQUIERE_MODIFICACION),
                self.evento(4, EstadoTramite.REQUIERE_MODIFICACION, EstadoTramite.EN_REVISION),
                self.evento(1, EstadoTramite.EN_REVISION, EstadoTramite.RECHAZADO),
            ],
        )
        self.assertEqual(resultado['dias_acumulados'], 3)
        self.assertEqual(resultado['color'], 'detenido')

    def test_sin_historial_usa_actualizacion_como_corte(self):
        informe = self.crear_informe(dias=10, estado=EstadoTramite.RECHAZADO)
        informe.fecha_actualizacion = self.ahora - timedelta(days=3)
        resultado = calcular_semaforo_informe(
            informe, limites=(7, 14), ahora=self.ahora, historial=[],
        )
        self.assertEqual(resultado['dias_acumulados'], 7)

    def test_fecha_futura_no_produce_dias_negativos(self):
        resultado = calcular_semaforo_informe(
            self.crear_informe(dias=-1), limites=(7, 14),
            ahora=self.ahora, historial=[],
        )
        self.assertEqual(resultado['dias'], 0)
        self.assertEqual(resultado['color'], 'verde')
