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