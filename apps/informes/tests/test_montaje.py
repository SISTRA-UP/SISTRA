"""Pruebas unitarias para el montaje de informe (SISTRA-06)."""

import threading
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import date

from apps.usuarios.models import Usuario, Rol, Permiso, RolPermiso
# Se agregaron Director y DirectorCarrera para las pruebas de concurrencia E4
from apps.personas.models import Estudiante, EstudianteCarrera, Director, DirectorCarrera
from apps.parametrizacion.models import Facultad, Carrera, PeriodoAcademico, EstadoPeriodo
from apps.propuestas.models import Propuesta, EstadoTramite
from apps.procesos.models import ProcesoTrabajoSocial
from apps.informes.models import Informe
from apps.seguimiento.models import Auditoria, HistorialEstado, Notificacion
from apps.propuestas.forms.aprobacion import RESULTADO_EXITO, RESULTADO_BLOQUEADO


TEXTO_VALIDO = 'A' * 100
TEXTO_CORTO = 'A' * 10
TEXTO_LARGO = 'A' * 1500


class MontajeInformeTests(TestCase):

    def setUp(self):
        self.client = Client()

        self.rol, _ = Rol.objects.get_or_create(
            nombre='Estudiante',
            defaults={'estado': 'Activo'}
        )

        self.usuario = Usuario.objects.create_user(
            correo_institucional='test@unipamplona.edu.co',
            nombre='Test User',
            cedula='12345678',
            nombre_usuario='test',
            password='testpass123',
            rol=self.rol,
            requiere_cambio_contrasena=False,
        )
        
        permiso_montar, _ = Permiso.objects.get_or_create(
            nombre='informe.montar',
            defaults={'descripcion': 'Permite al estudiante montar su informe'}
        )
        RolPermiso.objects.get_or_create(rol=self.rol, permiso=permiso_montar)
        
        self.estudiante = Estudiante.objects.create(usuario=self.usuario)

        self.facultad, _ = Facultad.objects.get_or_create(nombre='Facultad Test')
        self.carrera, _ = Carrera.objects.get_or_create(
            nombre='Carrera Test',
            defaults={'facultad': self.facultad, 'codigo': 'CT-TEST-1'}
        )

        self.est_carr = EstudianteCarrera.objects.create(
            estudiante=self.estudiante,
            carrera=self.carrera,
            estado='Activo',
        )

        self.periodo, _ = PeriodoAcademico.objects.get_or_create(
            nombre='2026-TEST',
            defaults={
                'fecha_inicio': date(2026, 1, 1),
                'fecha_fin': date(2026, 6, 30),
                'fecha_cierre_propuesta': date(2026, 3, 1),
                'fecha_cierre_informe': date(2026, 6, 1),
                'estado': EstadoPeriodo.CERRADO,
            }
        )

        self.proceso = ProcesoTrabajoSocial.objects.create(
            estudiante_carrera=self.est_carr,
            fecha_inicio=timezone.now(),
            estado='En curso',
        )

        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso,
            periodo_academico=self.periodo,
            codigo='PROP-TEST-1',
            titulo='Propuesta de Prueba',
            estado=EstadoTramite.APROBADO_EN_UP,
            resena_historica='x',
            identificacion_necesidad='x',
            justificacion='x',
            objetivos='x',
            referente_teorico='x',
            impacto_social='x',
            identificacion_poblacion='x',
            propuesta_social='x',
            entidad='x',
            poblacion_beneficiada='x',
            zona='x',
            area='x',
            sector='x',
            unidad='x',
        )

    def _login(self):
        self.client.force_login(self.usuario)

    def _crear_informe(self, estado):
        return Informe.objects.create(
            propuesta=self.propuesta,
            periodo_academico=self.periodo,
            codigo=f'INF-TEST-1-{estado[:3]}',
            estado=estado,
        )

    def test_redireccion_si_no_hay_login(self):
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 302)

    def test_acceso_denegado_sin_propuesta_aprobada(self):
        self._login()
        self.propuesta.estado = EstadoTramite.BORRADOR
        self.propuesta.save()
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Acceso no habilitado')

    def test_director_recibe_403(self):
        rol_director, _ = Rol.objects.get_or_create(nombre='Director', defaults={'estado': 'Activo'})
        usuario_director = Usuario.objects.create_user(
            correo_institucional='director@test.com', nombre='Director Test',
            cedula='9999999999', nombre_usuario='director', password='testpass123',
            rol=rol_director, requiere_cambio_contrasena=False,
        )
        self.client.force_login(usuario_director)
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 403)

    def test_acceso_exitoso_con_propuesta_aprobada(self):
        self._login()
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Crear Informe')
        self.assertEqual(Informe.objects.filter(propuesta=self.propuesta).count(), 0)
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Formulario de Informe')

    def test_get_no_crea_informe(self):
        self._login()
        self.assertEqual(Informe.objects.filter(propuesta=self.propuesta).count(), 0)
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Informe.objects.filter(propuesta=self.propuesta).count(), 0)
        self.assertContains(response, 'Crear Informe')

    def test_post_crear_informe_crea_uno_solo(self):
        self._login()
        response = self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Informe.objects.filter(propuesta=self.propuesta).count(), 1)
        informe = Informe.objects.get(propuesta=self.propuesta)
        self.assertEqual(informe.estado, EstadoTramite.BORRADOR)

    def test_dos_post_crear_informe_no_causan_error(self):
        self._login()
        response1 = self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        response2 = self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        self.assertEqual(Informe.objects.filter(propuesta=self.propuesta).count(), 1)
        self.assertNotEqual(response1.status_code, 500)
        self.assertNotEqual(response2.status_code, 500)

    def test_enviar_informe_cambia_estado(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        data = {'accion': 'enviar', 'resultados': TEXTO_VALIDO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)
        informe = Informe.objects.get(propuesta=self.propuesta)
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
        self.assertIsNotNone(informe.fecha_envio)

    def test_post_sobre_informe_en_revision_no_cambia_nada(self):
        self._login()
        informe = self._crear_informe(EstadoTramite.EN_REVISION)
        texto_original = informe.resultados
        data = {'accion': 'guardar_borrador', 'resultados': TEXTO_VALIDO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(informe.resultados, texto_original)
        self.assertTrue(Auditoria.objects.filter(id_registro_afectado=informe.id_informe, resultado=RESULTADO_BLOQUEADO).exists())

    def test_post_sobre_informe_aprobado_no_cambia_nada(self):
        self._login()
        informe = self._crear_informe(EstadoTramite.APROBADO)
        data = {'accion': 'guardar_borrador', 'resultados': TEXTO_VALIDO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.APROBADO)
        self.assertTrue(Auditoria.objects.filter(id_registro_afectado=informe.id_informe, resultado=RESULTADO_BLOQUEADO).exists())

    def test_formulario_bloqueado_si_esta_en_revision(self):
        self._login()
        self._crear_informe(EstadoTramite.EN_REVISION)
        response = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe bloqueado')

    def test_guardar_borrador_parcial(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        data = {'accion': 'guardar_borrador', 'resultados': TEXTO_VALIDO, 'conclusiones': '', 'recomendaciones': ''}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)
        informe = Informe.objects.get(propuesta=self.propuesta)
        self.assertEqual(informe.estado, EstadoTramite.BORRADOR)
        self.assertEqual(informe.resultados, TEXTO_VALIDO)

    def test_guardar_borrador_no_cambia_estado_requiere_modificacion(self):
        self._login()
        informe = self._crear_informe(EstadoTramite.REQUIERE_MODIFICACION)
        data = {'accion': 'guardar_borrador', 'resultados': TEXTO_VALIDO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)
        informe.refresh_from_db()
        self.assertEqual(informe.estado, EstadoTramite.REQUIERE_MODIFICACION)

    def test_reenvio_incrementa_version(self):
        self._login()
        informe = self._crear_informe(EstadoTramite.REQUIERE_MODIFICACION)
        self.assertEqual(informe.version_entrega, 1)
        data = {'accion': 'enviar', 'resultados': TEXTO_VALIDO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 302)
        informe.refresh_from_db()
        self.assertEqual(informe.version_entrega, 2)
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)

    def test_informe_rechazado_crea_nuevo(self):
        self._login()
        rechazado = self._crear_informe(EstadoTramite.RECHAZADO)
        response_get = self.client.get(reverse('informes:montaje'))
        self.assertEqual(response_get.status_code, 200)
        self.assertContains(response_get, 'Crear Informe')
        rechazado.refresh_from_db()
        self.assertEqual(rechazado.estado, EstadoTramite.RECHAZADO)
        self.assertEqual(Informe.objects.filter(propuesta=self.propuesta, estado=EstadoTramite.BORRADOR).count(), 0)
        response_post = self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        self.assertEqual(response_post.status_code, 302)
        nuevo = Informe.objects.filter(propuesta=self.propuesta, estado=EstadoTramite.BORRADOR).first()
        self.assertIsNotNone(nuevo)
        self.assertNotEqual(nuevo.codigo, rechazado.codigo)

    def test_mas_de_1000_caracteres_se_rechaza(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        data = {'accion': 'guardar_borrador', 'resultados': TEXTO_LARGO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Máximo')

    def test_menos_de_50_no_se_puede_enviar(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        data = {'accion': 'enviar', 'resultados': TEXTO_CORTO, 'conclusiones': TEXTO_CORTO, 'recomendaciones': TEXTO_CORTO}
        response = self.client.post(reverse('informes:montaje'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'mínimo 50 caracteres')

    def test_auditoria_al_crear_informe(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        informe = Informe.objects.filter(propuesta=self.propuesta).first()
        self.assertTrue(Auditoria.objects.filter(id_registro_afectado=informe.id_informe, accion='Crear informe').exists())

    def test_auditoria_al_guardar_borrador(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        data = {'accion': 'guardar_borrador', 'resultados': TEXTO_VALIDO, 'conclusiones': '', 'recomendaciones': ''}
        self.client.post(reverse('informes:montaje'), data)
        informe = Informe.objects.filter(propuesta=self.propuesta).first()
        self.assertTrue(Auditoria.objects.filter(id_registro_afectado=informe.id_informe, accion='Guardar borrador').exists())

    def test_auditoria_al_enviar_informe(self):
        self._login()
        self.client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        data = {'accion': 'enviar', 'resultados': TEXTO_VALIDO, 'conclusiones': TEXTO_VALIDO, 'recomendaciones': TEXTO_VALIDO}
        self.client.post(reverse('informes:montaje'), data)
        informe = Informe.objects.filter(propuesta=self.propuesta).first()
        self.assertTrue(Auditoria.objects.filter(id_registro_afectado=informe.id_informe, accion='Enviar informe').exists())


# ==============================================================================
# PRUEBAS DE CONCURRENCIA REAL (E3 y E4)
# Se usa TransactionTestCase porque TestCase envuelve todo en una transacción
# y no permite probar select_for_update() entre hilos reales de base de datos.
# ==============================================================================

class MontajeInformeConcurrenciaTests(TransactionTestCase):
    serialized_rollback = True
    
    def setUp(self):
        self.rol, _ = Rol.objects.get_or_create(nombre='Estudiante', defaults={'estado': 'Activo'})
        self.usuario = Usuario.objects.create_user(
            correo_institucional='conc@unipamplona.edu.co', nombre='Conc Test',
            cedula='12345679', nombre_usuario='conc', password='testpass123',
            rol=self.rol, requiere_cambio_contrasena=False,
        )
        permiso_montar, _ = Permiso.objects.get_or_create(
            nombre='informe.montar', defaults={'descripcion': 'Permite montar informe'}
        )
        RolPermiso.objects.get_or_create(rol=self.rol, permiso=permiso_montar)

        self.estudiante = Estudiante.objects.create(usuario=self.usuario)
        self.facultad, _ = Facultad.objects.get_or_create(nombre='Facultad Conc')
        self.carrera, _ = Carrera.objects.get_or_create(nombre='Carrera Conc', defaults={'facultad': self.facultad, 'codigo': 'CT-CONC-1'})
        self.est_carr = EstudianteCarrera.objects.create(estudiante=self.estudiante, carrera=self.carrera, estado='Activo')
        
        self.periodo, _ = PeriodoAcademico.objects.get_or_create(
            nombre='2026-CONC', 
            defaults={
                'fecha_inicio': date(2026, 1, 1), 
                'fecha_fin': date(2026, 6, 30),
                'fecha_cierre_propuesta': date(2026, 3, 1),
                'fecha_cierre_informe': date(2026, 6, 1),
                'estado': EstadoPeriodo.CERRADO
            }
        )
        
        self.proceso = ProcesoTrabajoSocial.objects.create(estudiante_carrera=self.est_carr, fecha_inicio=timezone.now(), estado='En curso')
        self.propuesta = Propuesta.objects.create(
            proceso=self.proceso, periodo_academico=self.periodo, codigo='PROP-CONC-1', titulo='Propuesta Conc',
            estado=EstadoTramite.APROBADO_EN_UP, resena_historica='x', identificacion_necesidad='x', justificacion='x',
            objetivos='x', referente_teorico='x', impacto_social='x', identificacion_poblacion='x', propuesta_social='x',
            entidad='x', poblacion_beneficiada='x', zona='x', area='x', sector='x', unidad='x',
        )

        # CORREGIDO: Crear Director y DirectorCarrera con fecha_inicio para que la vista pueda generar la notificación
        self.rol_director, _ = Rol.objects.get_or_create(nombre='Director', defaults={'estado': 'Activo'})
        self.usuario_director = Usuario.objects.create_user(
            correo_institucional='director_conc@unipamplona.edu.co', nombre='Director Conc',
            cedula='98765432', nombre_usuario='director_conc', password='testpass123',
            rol=self.rol_director, requiere_cambio_contrasena=False,
        )
        self.director = Director.objects.create(usuario=self.usuario_director)
        self.director_carrera = DirectorCarrera.objects.create(
            director=self.director,
            carrera=self.carrera,
            fecha_inicio=timezone.now(),  # <-- CAMBIO CLAVE: campo obligatorio
            activo=True
        )

    def test_dos_post_simultaneos_crear_informe_dejan_uno_solo(self):
        resultados = {}
        
        def hacer_post(nombre):
            client = Client()
            client.force_login(self.usuario)
            resp = client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
            resultados[nombre] = {
                'status': resp.status_code,
                'content': resp.content.decode('utf-8', errors='ignore')
            }

        barrera = threading.Barrier(2)
        def correr(nombre):
            barrera.wait()
            hacer_post(nombre)

        h1 = threading.Thread(target=correr, args=('h1',))
        h2 = threading.Thread(target=correr, args=('h2',))
        h1.start()
        h2.start()
        h1.join(timeout=30)
        h2.join(timeout=30)

        for nombre, r in resultados.items():
            self.assertNotEqual(r['status'], 500, f'{nombre} recibió 500 (race condition no protegida)')
            self.assertNotIn('Ocurrió un problema', r['content'], f'{nombre} recibió mensaje de error inesperado')

        self.assertEqual(
            Informe.objects.filter(propuesta=self.propuesta).count(), 1, 
            'Se crearon más de un informe (select_for_update no está protegiendo)'
        )
        
        self.assertEqual(
            Auditoria.objects.filter(accion='Crear informe', resultado=RESULTADO_EXITO).count(), 1, 
            'Se registraron múltiples auditorías de creación o ninguna con Éxito'
        )

    def test_dos_post_simultaneos_enviar_dejan_uno_solo(self):
        # 1. Crear informe primero de forma síncrona
        client = Client()
        client.force_login(self.usuario)
        client.post(reverse('informes:montaje'), {'accion': 'crear_informe'})
        
        resultados = {}
        data = {
            'accion': 'enviar',
            'resultados': TEXTO_VALIDO,
            'conclusiones': TEXTO_VALIDO,
            'recomendaciones': TEXTO_VALIDO
        }
        
        def hacer_post_envio(nombre):
            c = Client()
            c.force_login(self.usuario)
            resp = c.post(reverse('informes:montaje'), data)
            resultados[nombre] = {'status': resp.status_code}

        barrera = threading.Barrier(2)
        def correr_envio(nombre):
            barrera.wait()
            hacer_post_envio(nombre)

        h1 = threading.Thread(target=correr_envio, args=('h1',))
        h2 = threading.Thread(target=correr_envio, args=('h2',))
        h1.start()
        h2.start()
        h1.join(timeout=30)
        h2.join(timeout=30)

        informe = Informe.objects.get(propuesta=self.propuesta)
        
        # Validaciones E4
        self.assertEqual(informe.estado, EstadoTramite.EN_REVISION)
        self.assertEqual(informe.version_entrega, 1, 'La versión se duplicó por doble envío')
        
        self.assertEqual(
            HistorialEstado.objects.filter(informe=informe, tipo_accion='envio_informe').count(), 1, 
            'Se registraron múltiples historiales de envío'
        )
        
        self.assertEqual(
            Notificacion.objects.filter(informe=informe).count(), 1, 
            'Se enviaron múltiples notificaciones al director'
        )