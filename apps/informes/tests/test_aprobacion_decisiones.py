"""SISTRA-07 · Pruebas del guardado de decisiones."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cargue_up.models import CargueUp
from apps.informes.models import Informe
from apps.parametrizacion.models import (
    Carrera,
    Facultad,
    PeriodoAcademico,
    TipoRechazo,
)
from apps.personas.models import (
    Director,
    DirectorCarrera,
    Estudiante,
    EstudianteCarrera,
)
from apps.procesos.models import ProcesoTrabajoSocial
from apps.propuestas.models import EstadoTramite, Propuesta
from apps.seguimiento.models import (
    Auditoria,
    HistorialEstado,
    Notificacion,
)
from apps.usuarios.models import Rol


class DecisionInformeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        Usuario = get_user_model()

        cls.director = Usuario.objects.create_user(
            correo_institucional="director@example.com",
            nombre="Director de prueba",
            cedula="200000001",
            nombre_usuario="director_decisiones",
            password="ClavePruebas2026!",
            rol=Rol.objects.get(nombre="Director"),
            requiere_cambio_contrasena=False,
        )

        cls.estudiante = Usuario.objects.create_user(
            correo_institucional="estudiante@example.com",
            nombre="Estudiante de prueba",
            cedula="200000002",
            nombre_usuario="estudiante_decisiones",
            password="ClavePruebas2026!",
            rol=Rol.objects.get(nombre="Estudiante"),
            requiere_cambio_contrasena=False,
        )

        facultad = Facultad.objects.create(
            nombre="Facultad de pruebas",
        )

        cls.carrera = Carrera.objects.create(
            facultad=facultad,
            nombre="Carrera de pruebas",
            codigo="DEC-07",
        )

        perfil_director = Director.objects.create(
            usuario=cls.director,
        )

        cls.asignacion = DirectorCarrera.objects.create(
            director=perfil_director,
            carrera=cls.carrera,
            fecha_inicio=timezone.localdate(),
            activo=True,
        )

        perfil_estudiante = Estudiante.objects.create(
            usuario=cls.estudiante,
        )

        inscripcion = EstudianteCarrera.objects.create(
            estudiante=perfil_estudiante,
            carrera=cls.carrera,
            estado="Activo",
        )

        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado="En curso",
        )

        periodo = PeriodoAcademico.objects.create(
            nombre="Periodo de prueba",
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 12, 31),
            fecha_cierre_propuesta=date(2026, 6, 30),
            fecha_cierre_informe=date(2026, 12, 15),
            estado="Cerrado",
        )

        propuesta = Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=periodo,
            codigo="PROP-PRUEBA-07",
            titulo="Proyecto social de prueba",
            estado=EstadoTramite.APROBADO_EN_UP,
        )

        cls.informe = Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=periodo,
            codigo="INF-PRUEBA-07",
            resultados="Resultados de prueba",
            conclusiones="Conclusiones de prueba",
            recomendaciones="Recomendaciones de prueba",
            estado=EstadoTramite.EN_REVISION,
            fecha_envio=timezone.now(),
        )

        # Esta causal solo existe en la base temporal de pruebas.
        cls.tipo_rechazo = TipoRechazo.objects.create(
            nombre="Causal exclusiva de prueba",
            estado="Activo",
        )

    def setUp(self):
        self.client.force_login(self.director)

        self.url = reverse(
            "informes:decidir",
            kwargs={"id_informe": self.informe.pk},
        )

    def datos_decision(self, estado, **extras):
        self.informe.refresh_from_db()

        datos = {
            "nuevo_estado": estado,
            "fecha_actualizacion": (
                self.informe.fecha_actualizacion.isoformat()
            ),
        }

        datos.update(extras)
        return datos

    def comprobar_sin_cambios(self, estado):
        self.informe.refresh_from_db()

        self.assertEqual(self.informe.estado, estado)

        self.assertFalse(
            HistorialEstado.objects.filter(
                informe=self.informe,
            ).exists()
        )

        self.assertFalse(
            Notificacion.objects.filter(
                informe=self.informe,
            ).exists()
        )

    def test_aprobar_guarda_historial_aviso_y_auditoria(self):
        respuesta = self.client.post(
            self.url,
            self.datos_decision(EstadoTramite.APROBADO),
        )

        self.assertEqual(respuesta.status_code, 200)

        self.informe.refresh_from_db()

        self.assertEqual(
            self.informe.estado,
            EstadoTramite.APROBADO,
        )

        historial = HistorialEstado.objects.get(
            informe=self.informe,
        )

        self.assertEqual(
            historial.usuario_id,
            self.director.pk,
        )

        self.assertEqual(
            historial.estado_anterior,
            EstadoTramite.EN_REVISION,
        )

        self.assertEqual(
            historial.estado_nuevo,
            EstadoTramite.APROBADO,
        )

        aviso = Notificacion.objects.get(
            informe=self.informe,
        )

        self.assertEqual(
            aviso.usuario_id,
            self.estudiante.pk,
        )

        self.assertTrue(
            Auditoria.objects.filter(
                tabla_afectada="informe",
                id_registro_afectado=self.informe.pk,
                resultado="Exitoso",
            ).exists()
        )

    def test_modificacion_guarda_observacion(self):
        respuesta = self.client.post(
            self.url,
            self.datos_decision(
                EstadoTramite.REQUIERE_MODIFICACION,
                observacion="Amplía las conclusiones.",
            ),
        )

        self.assertEqual(respuesta.status_code, 200)

        historial = HistorialEstado.objects.get(
            informe=self.informe,
        )

        self.assertEqual(
            historial.observacion,
            "Amplía las conclusiones.",
        )

        self.informe.refresh_from_db()

        self.assertEqual(
            self.informe.estado,
            EstadoTramite.REQUIERE_MODIFICACION,
        )

    def test_rechazar_guarda_causal(self):
        respuesta = self.client.post(
            self.url,
            self.datos_decision(
                EstadoTramite.RECHAZADO,
                observacion="Motivo del rechazo de prueba.",
                tipo_rechazo=self.tipo_rechazo.pk,
            ),
        )

        self.assertEqual(respuesta.status_code, 200)

        historial = HistorialEstado.objects.get(
            informe=self.informe,
        )

        self.assertEqual(
            historial.tipo_rechazo_id,
            self.tipo_rechazo.pk,
        )

        self.informe.refresh_from_db()

        self.assertEqual(
            self.informe.estado,
            EstadoTramite.RECHAZADO,
        )

    def test_rechazo_incompleto_no_guarda(self):
        respuesta = self.client.post(
            self.url,
            self.datos_decision(EstadoTramite.RECHAZADO),
        )

        self.assertEqual(respuesta.status_code, 400)

        self.comprobar_sin_cambios(
            EstadoTramite.EN_REVISION,
        )

    def test_confirmacion_repetida_no_duplica_registros(self):
        datos = self.datos_decision(
            EstadoTramite.APROBADO,
        )

        primera = self.client.post(self.url, datos)
        segunda = self.client.post(self.url, datos)

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 409)

        self.assertEqual(
            HistorialEstado.objects.filter(
                informe=self.informe,
            ).count(),
            1,
        )

        self.assertEqual(
            Notificacion.objects.filter(
                informe=self.informe,
            ).count(),
            1,
        )

    def test_cambio_desde_aprobado_exige_justificacion(self):
        self.informe.estado = EstadoTramite.APROBADO
        self.informe.save()

        respuesta = self.client.post(
            self.url,
            self.datos_decision(
                EstadoTramite.REQUIERE_MODIFICACION,
                observacion="Corrige las conclusiones.",
            ),
        )

        self.assertEqual(respuesta.status_code, 400)

        self.comprobar_sin_cambios(
            EstadoTramite.APROBADO,
        )

    def test_cargue_up_bloquea_cambio_desde_aprobado(self):
        self.informe.estado = EstadoTramite.APROBADO
        self.informe.save()

        CargueUp.objects.create(
            informe=self.informe,
        )

        respuesta = self.client.post(
            self.url,
            self.datos_decision(
                EstadoTramite.REQUIERE_MODIFICACION,
                observacion="Corrige las conclusiones.",
                justificacion="Detecté un error después de aprobar.",
            ),
        )

        self.assertEqual(respuesta.status_code, 409)

        self.comprobar_sin_cambios(
            EstadoTramite.APROBADO,
        )

    def test_director_de_otra_carrera_no_puede_decidir(self):
        otra_carrera = Carrera.objects.create(
            facultad=self.carrera.facultad,
            nombre="Otra carrera",
            codigo="OTRA-07",
        )

        self.asignacion.carrera = otra_carrera
        self.asignacion.save(
            update_fields=["carrera"],
        )

        respuesta = self.client.post(
            self.url,
            self.datos_decision(EstadoTramite.APROBADO),
        )

        self.assertEqual(respuesta.status_code, 404)

        self.comprobar_sin_cambios(
            EstadoTramite.EN_REVISION,
        )

    def test_fallo_en_notificacion_deshace_la_decision(self):
        datos = self.datos_decision(
            EstadoTramite.APROBADO,
        )

        with patch(
            "apps.informes.views.aprobacion_decisiones."
            "Notificacion.objects.create",
            side_effect=RuntimeError("Fallo simulado"),
        ):
            with self.assertLogs(
                "apps.informes.views.aprobacion_decisiones",
                level="ERROR",
            ):
                respuesta = self.client.post(
                    self.url,
                    datos,
                )

        self.assertEqual(respuesta.status_code, 500)

        self.comprobar_sin_cambios(
            EstadoTramite.EN_REVISION,
        )

        self.assertFalse(
            Auditoria.objects.filter(
                tabla_afectada="informe",
                id_registro_afectado=self.informe.pk,
                resultado="Exitoso",
            ).exists()
        )

    def test_bandeja_muestra_detalle_del_informe(self):
        respuesta = self.client.get(
            reverse("informes:aprobacion")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertTemplateUsed(
            respuesta,
            "informes/aprobacion/detalle.html",
        )

        self.assertContains(respuesta, "Ver detalle")
        self.assertContains(respuesta, self.informe.codigo)
        self.assertContains(respuesta, "Resultados de prueba")
        self.assertContains(respuesta, "Conclusiones de prueba")
        self.assertContains(respuesta, "Recomendaciones de prueba")
        self.assertContains(respuesta, "Proyecto social de prueba")

        self.assertContains(
            respuesta,
            f'id="detalle-informe-{self.informe.pk}"',
        )

    def test_bandeja_no_muestra_informe_de_otra_carrera(self):
        otra_carrera = Carrera.objects.create(
            facultad=self.carrera.facultad,
            nombre="Carrera ajena al informe",
            codigo="AJENA-07",
        )

        self.asignacion.carrera = otra_carrera
        self.asignacion.save(update_fields=["carrera"])

        respuesta = self.client.get(
            reverse("informes:aprobacion")
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, self.informe.codigo)
        self.assertNotContains(respuesta, "Resultados de prueba")

        self.assertContains(
            respuesta,
            "No hay informes disponibles para revisar.",
        )

    def test_detalle_muestra_html_como_texto(self):
        self.informe.resultados = "<script>alert('prueba')</script>"
        self.informe.save(update_fields=["resultados"])

        respuesta = self.client.get(
            reverse("informes:aprobacion")
        )

        self.assertEqual(respuesta.status_code, 200)

        self.assertNotContains(
            respuesta,
            "<script>alert('prueba')</script>",
        )

        self.assertContains(
            respuesta,
            "&lt;script&gt;",
        )

    def test_filtro_estado_muestra_solo_coincidencias(self):
        url = reverse("informes:aprobacion")

        respuesta = self.client.get(
            url,
            {"estado": EstadoTramite.EN_REVISION},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, self.informe.codigo)

        respuesta = self.client.get(
            url,
            {"estado": EstadoTramite.REQUIERE_MODIFICACION},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, self.informe.codigo)
        self.assertEqual(
            respuesta.context["pagina"].paginator.count,
            0,
        )

    def test_filtro_color_coincide_con_el_semaforo(self):
        from datetime import timedelta

        ahora = timezone.now()
        url = reverse("informes:aprobacion")

        casos = [
            (0, "verde"),
            (7, "verde"),
            (8, "amarillo"),
            (14, "amarillo"),
            (15, "rojo"),
        ]

        with patch(
            "apps.informes.views.aprobacion.obtener_limites_semaforo",
            return_value=(7, 14),
        ):
            with patch(
                "apps.informes.views.aprobacion.timezone.now",
                return_value=ahora,
            ):
                for dias, esperado in casos:
                    self.informe.fecha_envio = (
                        ahora - timedelta(days=dias)
                    )
                    self.informe.save(update_fields=["fecha_envio"])

                    for color in ("verde", "amarillo", "rojo"):
                        with self.subTest(dias=dias, filtro=color):
                            respuesta = self.client.get(
                                url,
                                {"semaforo": color},
                            )

                            self.assertEqual(
                                respuesta.status_code,
                                200,
                            )

                            cantidad = (
                                respuesta.context["pagina"]
                                .paginator.count
                            )

                            self.assertEqual(
                                cantidad,
                                1 if color == esperado else 0,
                            )

                            if color == esperado:
                                fila = (
                                    respuesta.context["pagina"]
                                    .object_list[0]
                                )
                                self.assertEqual(
                                    fila.semaforo["color"],
                                    esperado,
                                )

    def test_filtro_color_excluye_informe_fuera_de_revision(self):
        self.informe.estado = EstadoTramite.REQUIERE_MODIFICACION
        self.informe.save(update_fields=["estado"])

        url = reverse("informes:aprobacion")

        for color in ("verde", "amarillo", "rojo"):
            with self.subTest(color=color):
                respuesta = self.client.get(
                    url,
                    {"semaforo": color},
                )

                self.assertEqual(respuesta.status_code, 200)
                self.assertNotContains(
                    respuesta,
                    self.informe.codigo,
                )
                self.assertEqual(
                    respuesta.context["pagina"].paginator.count,
                    0,
                )

    def test_busqueda_por_codigo_nombre_cedula_y_titulo(self):
        url = reverse("informes:aprobacion")

        terminos = [
            self.informe.codigo,
            self.estudiante.nombre,
            self.estudiante.cedula,
            self.informe.propuesta.titulo,
        ]

        for termino in terminos:
            with self.subTest(busqueda=termino):
                respuesta = self.client.get(
                    url,
                    {"buscar": termino},
                )

                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(
                    respuesta,
                    self.informe.codigo,
                )

        respuesta = self.client.get(
            url,
            {"buscar": "NO-EXISTE-ESTE-INFORME"},
        )

        self.assertEqual(
            respuesta.context["pagina"].paginator.count,
            0,
        )

    def test_reactivacion_permitida_no_modifica_el_informe(self):
        from apps.informes.forms.aprobacion_reactivacion import (
            validar_condiciones_reactivacion,
        )

        self.informe.estado = EstadoTramite.RECHAZADO
        self.informe.save(update_fields=["estado"])

        fecha_envio_anterior = self.informe.fecha_envio
        fecha_actualizacion_anterior = self.informe.fecha_actualizacion

        validar_condiciones_reactivacion(self.informe)

        self.comprobar_sin_cambios(EstadoTramite.RECHAZADO)

        self.assertEqual(
            self.informe.fecha_envio,
            fecha_envio_anterior,
        )
        self.assertEqual(
            self.informe.fecha_actualizacion,
            fecha_actualizacion_anterior,
        )

    def test_reactivacion_impide_informe_archivado(self):
        from django.core.exceptions import ValidationError
        from apps.informes.forms.aprobacion_reactivacion import (
            validar_condiciones_reactivacion,
        )

        self.informe.estado = EstadoTramite.RECHAZADO
        self.informe.archivado = True
        self.informe.fecha_archivado = timezone.now()
        self.informe.save()

        with self.assertRaises(ValidationError) as error:
            validar_condiciones_reactivacion(self.informe)

        self.assertEqual(
            error.exception.code,
            "informe_archivado",
        )
        self.comprobar_sin_cambios(EstadoTramite.RECHAZADO)

    def test_reactivacion_impide_estado_distinto_de_rechazado(self):
        from django.core.exceptions import ValidationError
        from apps.informes.forms.aprobacion_reactivacion import (
            validar_condiciones_reactivacion,
        )

        for estado in EstadoTramite.values:
            if estado == EstadoTramite.RECHAZADO:
                continue

            with self.subTest(estado=estado):
                self.informe.estado = estado
                self.informe.save(update_fields=["estado"])

                with self.assertRaises(ValidationError) as error:
                    validar_condiciones_reactivacion(self.informe)

                self.assertEqual(
                    error.exception.code,
                    "estado_no_rechazado",
                )
                self.comprobar_sin_cambios(estado)

    def test_reactivacion_impide_otro_informe_activo(self):
        from django.core.exceptions import ValidationError
        from apps.informes.forms.aprobacion_reactivacion import (
            validar_condiciones_reactivacion,
        )

        self.informe.estado = EstadoTramite.RECHAZADO
        self.informe.save(update_fields=["estado"])

        otro_informe = Informe.objects.create(
            propuesta=self.informe.propuesta,
            periodo_academico=self.informe.periodo_academico,
            codigo="INF-OTRO-ACTIVO-07",
            estado=EstadoTramite.BORRADOR,
        )

        with self.assertRaises(ValidationError) as error:
            validar_condiciones_reactivacion(self.informe)

        self.assertEqual(
            error.exception.code,
            "otro_informe_activo",
        )

        self.comprobar_sin_cambios(EstadoTramite.RECHAZADO)

        otro_informe.refresh_from_db()
        self.assertEqual(
            otro_informe.estado,
            EstadoTramite.BORRADOR,
        )

    def test_formulario_masivo_acepta_informe_autorizado(self):
        from apps.informes.forms.aprobacion_masiva import (
            DecisionMasivaInformeForm,
        )
        from apps.informes.views.aprobacion import (
            _informes_del_director,
        )

        formulario = DecisionMasivaInformeForm(
            data={
                "nuevo_estado": EstadoTramite.APROBADO,
                "informes": [str(self.informe.pk)],
            },
            informes_permitidos=_informes_del_director(self.director),
        )

        self.assertTrue(formulario.is_valid(), formulario.errors)

        self.assertEqual(
            list(
                formulario.cleaned_data["informes"].values_list(
                    "pk",
                    flat=True,
                )
            ),
            [self.informe.pk],
        )

        # Validar el formulario no debe aprobar ni notificar.
        self.comprobar_sin_cambios(EstadoTramite.EN_REVISION)

    def test_formulario_masivo_exige_seleccionar_informes(self):
        from apps.informes.forms.aprobacion_masiva import (
            DecisionMasivaInformeForm,
        )

        formulario = DecisionMasivaInformeForm(
            data={
                "nuevo_estado": EstadoTramite.APROBADO,
                "informes": [],
            },
            informes_permitidos=Informe.objects.filter(
                pk=self.informe.pk,
            ),
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("informes", formulario.errors)

    def test_formulario_masivo_rechaza_informe_fuera_de_autorizados(self):
        from apps.informes.forms.aprobacion_masiva import (
            DecisionMasivaInformeForm,
        )

        formulario = DecisionMasivaInformeForm(
            data={
                "nuevo_estado": EstadoTramite.APROBADO,
                "informes": [str(self.informe.pk)],
            },
            informes_permitidos=Informe.objects.none(),
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("informes", formulario.errors)
        self.comprobar_sin_cambios(EstadoTramite.EN_REVISION)

    def test_formulario_masivo_rechazo_exige_causal_y_observacion(self):
        from apps.informes.forms.aprobacion_masiva import (
            DecisionMasivaInformeForm,
        )

        formulario = DecisionMasivaInformeForm(
            data={
                "nuevo_estado": EstadoTramite.RECHAZADO,
                "informes": [str(self.informe.pk)],
                "observacion": "",
            },
            informes_permitidos=Informe.objects.filter(
                pk=self.informe.pk,
            ),
        )

        self.assertFalse(formulario.is_valid())
        self.assertIn("tipo_rechazo", formulario.errors)
        self.assertIn("observacion", formulario.errors)
        self.comprobar_sin_cambios(EstadoTramite.EN_REVISION)

    def crear_segundo_informe_para_masivo(self):
        """Crea otro estudiante e informe de la misma carrera."""

        Usuario = get_user_model()

        usuario = Usuario.objects.create_user(
            correo_institucional="segundo.masivo@example.com",
            nombre="Segundo estudiante masivo",
            cedula="200000009",
            nombre_usuario="segundo_masivo",
            password=None,
            rol=Rol.objects.get(nombre="Estudiante"),
            requiere_cambio_contrasena=False,
        )

        estudiante = Estudiante.objects.create(usuario=usuario)

        inscripcion = EstudianteCarrera.objects.create(
            estudiante=estudiante,
            carrera=self.carrera,
            estado="Activo",
        )

        proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=inscripcion,
            fecha_inicio=timezone.now(),
            estado="En curso",
        )

        propuesta = Propuesta.objects.create(
            proceso=proceso,
            periodo_academico=self.informe.periodo_academico,
            codigo="PROP-MASIVO-02",
            titulo="Segundo proyecto para prueba masiva",
            estado=EstadoTramite.APROBADO_EN_UP,
        )

        return Informe.objects.create(
            propuesta=propuesta,
            periodo_academico=self.informe.periodo_academico,
            codigo="INF-MASIVO-02",
            resultados="Resultados del segundo informe.",
            conclusiones="Conclusiones del segundo informe.",
            recomendaciones="Recomendaciones del segundo informe.",
            estado=EstadoTramite.EN_REVISION,
            fecha_envio=timezone.now(),
        )

    def datos_para_masivo(self, informes, estado, **extras):
        import json

        versiones = {}

        for informe in informes:
            informe.refresh_from_db()
            versiones[str(informe.pk)] = (
                informe.fecha_actualizacion.isoformat()
            )

        datos = {
            "nuevo_estado": estado,
            "informes": [str(informe.pk) for informe in informes],
            "versiones": json.dumps(versiones),
        }

        datos.update(extras)
        return datos

    def test_masivo_aprueba_dos_informes_y_notifica_a_cada_estudiante(self):
        segundo = self.crear_segundo_informe_para_masivo()
        informes = [self.informe, segundo]

        respuesta = self.client.post(
            reverse("informes:decidir_masivo"),
            self.datos_para_masivo(
                informes,
                EstadoTramite.APROBADO,
            ),
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["cantidad"], 2)

        for informe in informes:
            with self.subTest(informe=informe.codigo):
                informe.refresh_from_db()

                self.assertEqual(
                    informe.estado,
                    EstadoTramite.APROBADO,
                )

                historial = HistorialEstado.objects.get(
                    informe=informe,
                )

                self.assertEqual(
                    historial.estado_anterior,
                    EstadoTramite.EN_REVISION,
                )
                self.assertEqual(
                    historial.estado_nuevo,
                    EstadoTramite.APROBADO,
                )
                self.assertEqual(
                    historial.usuario_id,
                    self.director.pk,
                )

                aviso = Notificacion.objects.get(informe=informe)
                estudiante = (
                    informe.propuesta.proceso
                    .estudiante_carrera.estudiante.usuario
                )

                self.assertEqual(aviso.usuario_id, estudiante.pk)

                self.assertEqual(
                    Auditoria.objects.filter(
                        accion="decision_masiva_informe",
                        tabla_afectada="informe",
                        id_registro_afectado=informe.pk,
                        resultado="Exitoso",
                    ).count(),
                    1,
                )

    def test_masivo_rechaza_dos_informes_con_causal_y_observacion(self):
        segundo = self.crear_segundo_informe_para_masivo()
        informes = [self.informe, segundo]

        respuesta = self.client.post(
            reverse("informes:decidir_masivo"),
            self.datos_para_masivo(
                informes,
                EstadoTramite.RECHAZADO,
                tipo_rechazo=self.tipo_rechazo.pk,
                observacion="Observación de rechazo para la selección.",
            ),
        )

        self.assertEqual(respuesta.status_code, 200)

        for informe in informes:
            informe.refresh_from_db()
            self.assertEqual(informe.estado, EstadoTramite.RECHAZADO)

            historial = HistorialEstado.objects.get(informe=informe)

            self.assertEqual(
                historial.tipo_rechazo_id,
                self.tipo_rechazo.pk,
            )
            self.assertEqual(
                historial.observacion,
                "Observación de rechazo para la selección.",
            )
            self.assertEqual(
                Notificacion.objects.filter(informe=informe).count(),
                1,
            )

    def test_masivo_repetido_no_duplica_historial_ni_avisos(self):
        segundo = self.crear_segundo_informe_para_masivo()

        datos = self.datos_para_masivo(
            [self.informe, segundo],
            EstadoTramite.APROBADO,
        )
        url = reverse("informes:decidir_masivo")

        primera = self.client.post(url, datos)
        segunda = self.client.post(url, datos)

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 409)

        for informe in [self.informe, segundo]:
            self.assertEqual(
                HistorialEstado.objects.filter(informe=informe).count(),
                1,
            )
            self.assertEqual(
                Notificacion.objects.filter(informe=informe).count(),
                1,
            )

    def test_masivo_con_version_antigua_no_modifica_ninguno(self):
        segundo = self.crear_segundo_informe_para_masivo()

        datos = self.datos_para_masivo(
            [self.informe, segundo],
            EstadoTramite.APROBADO,
        )

        # Simula un cambio posterior a la apertura de la pantalla.
        from datetime import timedelta

        Informe.objects.filter(pk=segundo.pk).update(
            fecha_actualizacion=(
                segundo.fecha_actualizacion + timedelta(seconds=1)
            )
        )

        respuesta = self.client.post(
            reverse("informes:decidir_masivo"),
            datos,
        )

        self.assertEqual(respuesta.status_code, 409)

        for informe in [self.informe, segundo]:
            informe.refresh_from_db()
            self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
            self.assertFalse(
                HistorialEstado.objects.filter(informe=informe).exists()
            )
            self.assertFalse(
                Notificacion.objects.filter(informe=informe).exists()
            )

    def test_masivo_fallo_en_segundo_aviso_deshace_toda_la_operacion(self):
        segundo = self.crear_segundo_informe_para_masivo()
        informes = [self.informe, segundo]

        datos = self.datos_para_masivo(
            informes,
            EstadoTramite.APROBADO,
        )

        crear_aviso_original = Notificacion.objects.create
        llamadas = []

        def crear_aviso_con_fallo(*args, **kwargs):
            llamadas.append(kwargs["informe"].pk)

            if len(llamadas) == 2:
                raise RuntimeError("Fallo simulado en el segundo aviso")

            return crear_aviso_original(*args, **kwargs)

        with patch(
            "apps.informes.views.aprobacion_masiva."
            "Notificacion.objects.create",
            side_effect=crear_aviso_con_fallo,
        ):
            with self.assertLogs(
                "apps.informes.views.aprobacion_masiva",
                level="ERROR",
            ):
                respuesta = self.client.post(
                    reverse("informes:decidir_masivo"),
                    datos,
                )

        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(len(llamadas), 2)

        for informe in informes:
            informe.refresh_from_db()
            self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)

            self.assertFalse(
                HistorialEstado.objects.filter(informe=informe).exists()
            )
            self.assertFalse(
                Notificacion.objects.filter(informe=informe).exists()
            )
            self.assertFalse(
                Auditoria.objects.filter(
                    accion="decision_masiva_informe",
                    tabla_afectada="informe",
                    id_registro_afectado=informe.pk,
                ).exists()
            )
    def preparar_rechazado_para_reactivar(self):
        from datetime import timedelta

        ahora = timezone.now()

        self.informe.estado = EstadoTramite.RECHAZADO
        self.informe.fecha_envio = ahora - timedelta(days=13)
        self.informe.save()

        # Acumuló 10 días en revisión y lleva 3 días rechazado.
        HistorialEstado.objects.create(
            informe=self.informe,
            usuario=self.director,
            estado_anterior=EstadoTramite.EN_REVISION,
            estado_nuevo=EstadoTramite.RECHAZADO,
            tipo_rechazo=self.tipo_rechazo,
            observacion="Rechazo de prueba.",
            tipo_accion="decision_informe",
            fecha_hora=ahora - timedelta(days=3),
        )

        return {
            "motivo": "El rechazo fue registrado por error.",
            "fecha_actualizacion": (
                self.informe.fecha_actualizacion.isoformat()
            ),
        }

    def test_reactivar_guarda_historial_aviso_y_conserva_dias(self):
        from apps.informes.views.aprobacion_semaforo import (
            calcular_semaforo_informe,
        )

        datos = self.preparar_rechazado_para_reactivar()
        fecha_original = self.informe.fecha_envio
        entrega_original = self.informe.version_entrega

        respuesta = self.client.post(
            reverse(
                "informes:reactivar",
                kwargs={"id_informe": self.informe.pk},
            ),
            datos,
        )

        self.assertEqual(respuesta.status_code, 200)

        self.informe.refresh_from_db()
        self.assertEqual(
            self.informe.estado,
            EstadoTramite.EN_REVISION,
        )
        self.assertEqual(self.informe.fecha_envio, fecha_original)
        self.assertEqual(self.informe.version_entrega, entrega_original)

        self.assertEqual(
            HistorialEstado.objects.filter(
                informe=self.informe,
            ).count(),
            2,
        )

        reactivacion = HistorialEstado.objects.get(
            informe=self.informe,
            tipo_accion="reactivacion_informe",
        )

        self.assertEqual(
            reactivacion.motivo_reactivacion,
            datos["motivo"],
        )
        self.assertEqual(
            reactivacion.estado_anterior,
            EstadoTramite.RECHAZADO,
        )
        self.assertEqual(
            reactivacion.estado_nuevo,
            EstadoTramite.EN_REVISION,
        )

        aviso = Notificacion.objects.get(informe=self.informe)
        self.assertEqual(aviso.usuario_id, self.estudiante.pk)

        semaforo = calcular_semaforo_informe(
            self.informe,
            limites=(7, 14),
            ahora=reactivacion.fecha_hora,
        )

        self.assertEqual(semaforo["dias"], 10)
        self.assertEqual(semaforo["color"], "amarillo")

        self.assertTrue(
            Auditoria.objects.filter(
                accion="reactivacion_informe",
                id_registro_afectado=self.informe.pk,
                resultado="Exitoso",
            ).exists()
        )

    def test_reactivar_sin_motivo_no_guarda(self):
        datos = self.preparar_rechazado_para_reactivar()
        datos["motivo"] = "   "

        respuesta = self.client.post(
            reverse(
                "informes:reactivar",
                kwargs={"id_informe": self.informe.pk},
            ),
            datos,
        )

        self.assertEqual(respuesta.status_code, 400)

        self.informe.refresh_from_db()
        self.assertEqual(self.informe.estado, EstadoTramite.RECHAZADO)
        self.assertEqual(
            HistorialEstado.objects.filter(informe=self.informe).count(),
            1,
        )
        self.assertFalse(
            Notificacion.objects.filter(informe=self.informe).exists()
        )

    def test_reactivar_dos_veces_no_duplica_registros(self):
        datos = self.preparar_rechazado_para_reactivar()

        url = reverse(
            "informes:reactivar",
            kwargs={"id_informe": self.informe.pk},
        )

        primera = self.client.post(url, datos)
        segunda = self.client.post(url, datos)

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 409)

        self.assertEqual(
            HistorialEstado.objects.filter(
                informe=self.informe,
                tipo_accion="reactivacion_informe",
            ).count(),
            1,
        )
        self.assertEqual(
            Notificacion.objects.filter(informe=self.informe).count(),
            1,
        )

    def test_endpoint_reactivar_bloquea_otro_informe_activo(self):
        datos = self.preparar_rechazado_para_reactivar()

        Informe.objects.create(
            propuesta=self.informe.propuesta,
            periodo_academico=self.informe.periodo_academico,
            codigo="INF-NUEVO-ACTIVO-REACT",
            estado=EstadoTramite.BORRADOR,
        )

        respuesta = self.client.post(
            reverse(
                "informes:reactivar",
                kwargs={"id_informe": self.informe.pk},
            ),
            datos,
        )

        self.assertEqual(respuesta.status_code, 409)

        self.informe.refresh_from_db()
        self.assertEqual(self.informe.estado, EstadoTramite.RECHAZADO)
        self.assertFalse(
            HistorialEstado.objects.filter(
                informe=self.informe,
                tipo_accion="reactivacion_informe",
            ).exists()
        )
        self.assertFalse(
            Notificacion.objects.filter(informe=self.informe).exists()
        )

    def test_endpoint_reactivar_no_permite_informe_archivado(self):
        datos = self.preparar_rechazado_para_reactivar()

        self.informe.archivado = True
        self.informe.fecha_archivado = timezone.now()
        self.informe.save()

        datos["fecha_actualizacion"] = (
            self.informe.fecha_actualizacion.isoformat()
        )

        respuesta = self.client.post(
            reverse(
                "informes:reactivar",
                kwargs={"id_informe": self.informe.pk},
            ),
            datos,
        )

        # La consulta autorizada excluye los informes archivados.
        self.assertEqual(respuesta.status_code, 404)

        self.informe.refresh_from_db()
        self.assertEqual(self.informe.estado, EstadoTramite.RECHAZADO)
        self.assertFalse(
            Notificacion.objects.filter(informe=self.informe).exists()
        )
    def preparar_dos_rechazados_para_masivo(self):
        import json
        from datetime import timedelta

        segundo = self.crear_segundo_informe_para_masivo()
        informes = [self.informe, segundo]
        ahora = timezone.now()

        for informe in informes:
            informe.estado = EstadoTramite.RECHAZADO
            informe.fecha_envio = ahora - timedelta(days=13)
            informe.save()

            HistorialEstado.objects.create(
                informe=informe,
                usuario=self.director,
                estado_anterior=EstadoTramite.EN_REVISION,
                estado_nuevo=EstadoTramite.RECHAZADO,
                tipo_rechazo=self.tipo_rechazo,
                observacion="Rechazo de prueba.",
                tipo_accion="decision_informe",
                fecha_hora=ahora - timedelta(days=3),
            )

        datos = {
            "motivo": "Los rechazos se registraron por error.",
            "informes": [str(informe.pk) for informe in informes],
            "versiones": json.dumps({
                str(informe.pk): informe.fecha_actualizacion.isoformat()
                for informe in informes
            }),
        }

        return informes, datos

    def comprobar_reactivacion_masiva_sin_cambios(self, informes):
        for informe in informes:
            informe.refresh_from_db()

            self.assertEqual(
                informe.estado,
                EstadoTramite.RECHAZADO,
            )
            self.assertEqual(
                HistorialEstado.objects.filter(informe=informe).count(),
                1,
            )
            self.assertFalse(
                Notificacion.objects.filter(informe=informe).exists()
            )
            self.assertFalse(
                Auditoria.objects.filter(
                    accion="reactivacion_masiva_informe",
                    tabla_afectada="informe",
                    id_registro_afectado=informe.pk,
                ).exists()
            )

    def test_reactivacion_masiva_conserva_dias_y_notifica(self):
        from apps.informes.views.aprobacion_semaforo import (
            calcular_semaforo_informe,
        )

        informes, datos = self.preparar_dos_rechazados_para_masivo()

        fechas_originales = {
            informe.pk: informe.fecha_envio
            for informe in informes
        }
        entregas_originales = {
            informe.pk: informe.version_entrega
            for informe in informes
        }

        respuesta = self.client.post(
            reverse("informes:reactivar_masivo"),
            datos,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()["cantidad"], 2)

        for informe in informes:
            with self.subTest(informe=informe.codigo):
                informe.refresh_from_db()

                self.assertEqual(
                    informe.estado,
                    EstadoTramite.EN_REVISION,
                )
                self.assertEqual(
                    informe.fecha_envio,
                    fechas_originales[informe.pk],
                )
                self.assertEqual(
                    informe.version_entrega,
                    entregas_originales[informe.pk],
                )

                self.assertEqual(
                    HistorialEstado.objects.filter(informe=informe).count(),
                    2,
                )

                evento = HistorialEstado.objects.get(
                    informe=informe,
                    tipo_accion="reactivacion_masiva_informe",
                )

                self.assertEqual(
                    evento.motivo_reactivacion,
                    datos["motivo"],
                )
                self.assertEqual(
                    evento.estado_anterior,
                    EstadoTramite.RECHAZADO,
                )
                self.assertEqual(
                    evento.estado_nuevo,
                    EstadoTramite.EN_REVISION,
                )

                aviso = Notificacion.objects.get(informe=informe)
                estudiante = (
                    informe.propuesta.proceso
                    .estudiante_carrera.estudiante.usuario
                )
                self.assertEqual(aviso.usuario_id, estudiante.pk)

                semaforo = calcular_semaforo_informe(
                    informe,
                    limites=(7, 14),
                    ahora=evento.fecha_hora,
                )

                self.assertEqual(semaforo["dias"], 10)
                self.assertEqual(semaforo["color"], "amarillo")

                self.assertEqual(
                    Auditoria.objects.filter(
                        accion="reactivacion_masiva_informe",
                        tabla_afectada="informe",
                        id_registro_afectado=informe.pk,
                        resultado="Exitoso",
                    ).count(),
                    1,
                )

    def test_reactivacion_masiva_sin_motivo_no_guarda(self):
        informes, datos = self.preparar_dos_rechazados_para_masivo()
        datos["motivo"] = "   "

        respuesta = self.client.post(
            reverse("informes:reactivar_masivo"),
            datos,
        )

        self.assertEqual(respuesta.status_code, 400)
        self.comprobar_reactivacion_masiva_sin_cambios(informes)

    def test_reactivacion_masiva_repetida_no_duplica_registros(self):
        informes, datos = self.preparar_dos_rechazados_para_masivo()
        url = reverse("informes:reactivar_masivo")

        primera = self.client.post(url, datos)
        segunda = self.client.post(url, datos)

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 409)

        for informe in informes:
            self.assertEqual(
                HistorialEstado.objects.filter(
                    informe=informe,
                    tipo_accion="reactivacion_masiva_informe",
                ).count(),
                1,
            )
            self.assertEqual(
                Notificacion.objects.filter(informe=informe).count(),
                1,
            )

    def test_reactivacion_masiva_bloquea_todo_si_hay_otro_activo(self):
        informes, datos = self.preparar_dos_rechazados_para_masivo()
        segundo = informes[1]

        Informe.objects.create(
            propuesta=segundo.propuesta,
            periodo_academico=segundo.periodo_academico,
            codigo="INF-ACTIVO-BLOQUEO-MASIVO",
            estado=EstadoTramite.BORRADOR,
        )

        respuesta = self.client.post(
            reverse("informes:reactivar_masivo"),
            datos,
        )

        self.assertEqual(respuesta.status_code, 409)
        self.comprobar_reactivacion_masiva_sin_cambios(informes)

    def test_reactivacion_masiva_fallo_en_segundo_aviso_deshace_todo(self):
        informes, datos = self.preparar_dos_rechazados_para_masivo()

        crear_aviso_original = Notificacion.objects.create
        llamadas = []

        def crear_aviso_con_fallo(*args, **kwargs):
            llamadas.append(kwargs["informe"].pk)

            if len(llamadas) == 2:
                raise RuntimeError("Fallo simulado en el segundo aviso")

            return crear_aviso_original(*args, **kwargs)

        with patch(
            "apps.informes.views.aprobacion_reactivacion_masiva."
            "Notificacion.objects.create",
            side_effect=crear_aviso_con_fallo,
        ):
            with self.assertLogs(
                "apps.informes.views.aprobacion_reactivacion_masiva",
                level="ERROR",
            ):
                respuesta = self.client.post(
                    reverse("informes:reactivar_masivo"),
                    datos,
                )

        self.assertEqual(respuesta.status_code, 500)
        self.assertEqual(len(llamadas), 2)
        self.comprobar_reactivacion_masiva_sin_cambios(informes)
    def test_auditoria_registra_decision_con_datos_incompletos(self):
        respuesta = self.client.post(
            self.url,
            self.datos_decision(EstadoTramite.RECHAZADO),
        )

        self.assertEqual(respuesta.status_code, 400)
        self.comprobar_sin_cambios(EstadoTramite.EN_REVISION)

        registro = Auditoria.objects.get(
            accion="intento_decision_informe",
            id_registro_afectado=self.informe.pk,
        )

        self.assertEqual(registro.usuario_id, self.director.pk)
        self.assertEqual(registro.resultado, "Fallido")
        self.assertIn("HTTP 400", registro.detalle)

    def test_auditoria_registra_intento_de_estudiante(self):
        self.client.force_login(self.estudiante)

        respuesta = self.client.post(
            self.url,
            self.datos_decision(EstadoTramite.APROBADO),
        )

        self.assertEqual(respuesta.status_code, 403)
        self.comprobar_sin_cambios(EstadoTramite.EN_REVISION)

        registro = Auditoria.objects.get(
            accion="intento_decision_informe",
            id_registro_afectado=self.informe.pk,
        )

        self.assertEqual(registro.usuario_id, self.estudiante.pk)
        self.assertEqual(registro.resultado, "Bloqueado")
        self.assertIn("HTTP 403", registro.detalle)