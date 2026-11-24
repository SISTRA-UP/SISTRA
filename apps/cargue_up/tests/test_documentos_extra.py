"""PRO-16 · Cargue de archivos restantes («Documentos extra»): pruebas."""

import shutil
import tempfile

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.cargue_up.forms import documentos_extra as servicio
from apps.cargue_up.models import DocumentoExtra
from apps.cargue_up.tests.test_verificacion_informe import BaseVerificacionTests
from apps.parametrizacion import servicios as parametros
from apps.procesos.models import EstadoAvance
from apps.propuestas.models import EstadoTramite
from apps.seguimiento.models import Auditoria, Notificacion

MEDIA_PRUEBAS = tempfile.mkdtemp(prefix='sistra_pro16_')


def pdf(nombre='evidencia.pdf', contenido=b'%PDF-1.4\n%prueba\n'):
    return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')


@override_settings(MEDIA_ROOT=MEDIA_PRUEBAS)
class BaseDocumentosExtraTests(BaseVerificacionTests):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_PRUEBAS, ignore_errors=True)

    def setUp(self):
        self.informe = self.crear_informe('pro16', estado=EstadoTramite.APROBADO_EN_UP, con_cargue=False)
        self.proceso = self.informe.propuesta.proceso
        self.estudiante = self.proceso.estudiante_carrera.estudiante.usuario
        self.client.force_login(self.estudiante)

    def subir(self, archivo=None):
        return self.client.post(
            reverse('cargue_up:documentos_extra_subir'), {'archivo': archivo or pdf()}, follow=True
        )

    def finalizar(self):
        return self.client.post(reverse('cargue_up:documentos_extra_finalizar'), follow=True)

    def mensajes(self, respuesta):
        return [str(m) for m in respuesta.context['messages']]

    def pantalla(self):
        return self.client.get(reverse('cargue_up:cargue_propuesta'))


class PanelTests(BaseDocumentosExtraTests):
    def test_el_panel_aparece_con_el_informe_aprobado_en_up(self):
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'id="documentos-extra"')
        self.assertContains(respuesta, 'certificado de horas, evidencias, etc.')
        self.assertContains(respuesta, '0 de 4')

    def test_el_panel_no_aparece_antes_de_aprobado_en_up(self):
        for estado in (EstadoTramite.APROBADO, EstadoTramite.SUBIDO_EN_UP):
            with self.subTest(estado=estado):
                self.informe.estado = estado
                self.informe.save()
                self.assertNotContains(self.pantalla(), 'id="documentos-extra"')

    def test_finalizado_muestra_los_documentos_sin_cargar_ni_quitar(self):
        self.subir()
        self.finalizar()
        respuesta = self.pantalla()
        self.assertContains(respuesta, 'Proceso finalizado')
        self.assertContains(respuesta, 'evidencia.pdf')
        self.assertNotContains(respuesta, reverse('cargue_up:documentos_extra_subir'))
        self.assertNotContains(respuesta, '>Quitar<')


class SubirTests(BaseDocumentosExtraTests):
    def test_carga_un_pdf_valido(self):
        respuesta = self.subir(pdf('Certificado de horas.pdf'))
        self.assertIn(servicio.MSG_16_01.format(nombre='Certificado de horas.pdf'), self.mensajes(respuesta))
        documento = DocumentoExtra.objects.get(informe=self.informe)
        self.assertEqual(documento.usuario, self.estudiante)
        self.assertTrue(default_storage.exists(documento.ruta_archivo))
        self.assertTrue(Auditoria.objects.filter(
            accion=servicio.ACCION_SUBIR, resultado=servicio.RESULTADO_EXITO,
            id_registro_afectado=documento.pk).exists())

    def test_rechaza_lo_que_no_es_pdf(self):
        casos = {
            'extension': pdf('foto.png'),
            'contenido': pdf('falso.pdf', b'MZ\x90\x00 no soy un pdf'),
        }
        for caso, archivo in casos.items():
            with self.subTest(caso=caso):
                respuesta = self.subir(archivo)
                self.assertIn(servicio.MSG_16_04, self.mensajes(respuesta))
        self.assertFalse(DocumentoExtra.objects.exists())

    def test_rechaza_un_archivo_vacio(self):
        respuesta = self.subir(pdf('vacio.pdf', b''))
        self.assertIn(servicio.MSG_16_10, self.mensajes(respuesta))
        self.assertFalse(DocumentoExtra.objects.exists())

    def test_respeta_el_tamano_maximo_de_la_parametrizacion(self):
        parametros.guardar(servicio.CLAVE_MAX_MB, '1', self.administrador)
        grande = b'%PDF-' + b'0' * (1024 * 1024)
        respuesta = self.subir(pdf('grande.pdf', grande))
        self.assertIn(servicio.MSG_16_05.format(mb=1), self.mensajes(respuesta))
        self.assertFalse(DocumentoExtra.objects.exists())

    def test_el_tamano_por_defecto_es_10_mb(self):
        self.assertEqual(servicio.max_mb(), 10)

    def test_maximo_cuatro_documentos(self):
        for numero in range(4):
            self.subir(pdf(f'evidencia{numero}.pdf'))
        respuesta = self.subir(pdf('quinto.pdf'))
        self.assertIn(servicio.MSG_16_06.format(maximo=4), self.mensajes(respuesta))
        self.assertEqual(DocumentoExtra.objects.filter(informe=self.informe).count(), 4)
        self.assertContains(self.pantalla(), 'Ya cargaste el máximo de 4 documentos')

    def test_no_se_carga_si_el_informe_no_esta_aprobado_en_up(self):
        self.informe.estado = EstadoTramite.SUBIDO_EN_UP
        self.informe.save()
        respuesta = self.subir()
        self.assertIn(servicio.MSG_16_08, self.mensajes(respuesta))
        self.assertFalse(DocumentoExtra.objects.exists())
        self.assertTrue(Auditoria.objects.filter(
            accion=servicio.ACCION_SUBIR, resultado=servicio.RESULTADO_BLOQUEADO).exists())

    def test_el_nombre_se_limpia_de_rutas_y_se_recorta(self):
        self.assertEqual(servicio.nombre_seguro('C:\\Users\\x\\aval.pdf'), 'aval.pdf')
        self.assertEqual(servicio.nombre_seguro('../../etc/aval.pdf'), 'aval.pdf')
        largo = servicio.nombre_seguro('a' * 300 + '.pdf')
        self.assertEqual(len(largo), servicio.LONGITUD_NOMBRE)
        self.assertTrue(largo.endswith('.pdf'))

    def test_el_archivo_se_guarda_con_un_nombre_generado(self):
        self.subir(pdf('../../malicioso.pdf'))
        documento = DocumentoExtra.objects.get()
        self.assertTrue(documento.ruta_archivo.startswith('documentos_extra/'))
        self.assertNotIn('malicioso', documento.ruta_archivo)

    def test_sin_permiso_de_estudiante_no_se_carga(self):
        self.client.force_login(self.director)
        respuesta = self.client.post(reverse('cargue_up:documentos_extra_subir'), {'archivo': pdf()})
        self.assertEqual(respuesta.status_code, 403)

    def test_solo_acepta_post(self):
        self.assertEqual(self.client.get(reverse('cargue_up:documentos_extra_subir')).status_code, 405)


class QuitarTests(BaseDocumentosExtraTests):
    def test_quita_el_documento_y_su_archivo(self):
        self.subir()
        documento = DocumentoExtra.objects.get()
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(
                reverse('cargue_up:documentos_extra_quitar', args=[documento.pk]), follow=True
            )
        self.assertIn(servicio.MSG_16_02.format(nombre='evidencia.pdf'), self.mensajes(respuesta))
        self.assertFalse(DocumentoExtra.objects.exists())
        self.assertFalse(default_storage.exists(documento.ruta_archivo))

    def test_no_se_quita_el_documento_de_otro_estudiante(self):
        otro = self.crear_informe('otro16', estado=EstadoTramite.APROBADO_EN_UP, con_cargue=False)
        ajeno = DocumentoExtra.objects.create(
            informe=otro, usuario=otro.propuesta.proceso.estudiante_carrera.estudiante.usuario,
            nombre_archivo='ajeno.pdf', ruta_archivo='documentos_extra/ajeno.pdf', tamano_bytes=10,
        )
        respuesta = self.client.post(
            reverse('cargue_up:documentos_extra_quitar', args=[ajeno.pk]), follow=True
        )
        self.assertIn(servicio.MSG_16_08, self.mensajes(respuesta))
        self.assertTrue(DocumentoExtra.objects.filter(pk=ajeno.pk).exists())

    def test_despues_de_finalizar_no_se_quita(self):
        self.subir()
        self.finalizar()
        documento = DocumentoExtra.objects.get()
        respuesta = self.client.post(
            reverse('cargue_up:documentos_extra_quitar', args=[documento.pk]), follow=True
        )
        self.assertIn(servicio.MSG_16_08, self.mensajes(respuesta))
        self.assertTrue(DocumentoExtra.objects.filter(pk=documento.pk).exists())


class FinalizarTests(BaseDocumentosExtraTests):
    def test_finaliza_el_proceso_y_avisa_al_director(self):
        self.subir()
        self.subir(pdf('certificado.pdf'))
        respuesta = self.finalizar()
        self.assertIn(servicio.MSG_16_03, self.mensajes(respuesta))
        self.proceso.refresh_from_db()
        self.assertEqual(self.proceso.estado, EstadoAvance.FINALIZADA)
        self.assertIsNotNone(self.proceso.fecha_finalizacion)
        aviso = Notificacion.objects.get(usuario=self.director, tipo=servicio.TIPO_NOTIFICACION)
        self.assertEqual(aviso.informe, self.informe)
        self.assertIn('2 documento(s)', aviso.mensaje)
        self.assertTrue(Auditoria.objects.filter(
            accion=servicio.ACCION_FINALIZAR, resultado=servicio.RESULTADO_EXITO).exists())

    def test_sin_documentos_no_se_finaliza(self):
        respuesta = self.finalizar()
        self.assertIn(servicio.MSG_16_07, self.mensajes(respuesta))
        self.proceso.refresh_from_db()
        self.assertEqual(self.proceso.estado, 'En curso')
        self.assertFalse(Notificacion.objects.filter(tipo=servicio.TIPO_NOTIFICACION).exists())

    def test_finalizar_dos_veces_avisa_una_sola_vez(self):
        self.subir()
        self.finalizar()
        respuesta = self.finalizar()
        self.assertIn(servicio.MSG_16_08, self.mensajes(respuesta))
        self.assertEqual(Notificacion.objects.filter(tipo=servicio.TIPO_NOTIFICACION).count(), 1)

    def test_despues_de_finalizar_no_se_carga(self):
        self.subir()
        self.finalizar()
        respuesta = self.subir(pdf('tarde.pdf'))
        self.assertIn(servicio.MSG_16_08, self.mensajes(respuesta))
        self.assertEqual(DocumentoExtra.objects.count(), 1)


class DescargaYDirectorTests(BaseDocumentosExtraTests):
    def setUp(self):
        super().setUp()
        self.subir(pdf('aval.pdf', b'%PDF-1.4 contenido del aval'))
        self.documento = DocumentoExtra.objects.get()
        self.url_descarga = reverse('cargue_up:documentos_extra_descargar', args=[self.documento.pk])

    def test_el_estudiante_descarga_su_documento(self):
        respuesta = self.client.get(self.url_descarga)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(b''.join(respuesta.streaming_content), b'%PDF-1.4 contenido del aval')
        self.assertIn('aval.pdf', respuesta['Content-Disposition'])

    def test_el_director_de_la_carrera_descarga(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(self.url_descarga).status_code, 200)

    def test_otros_reciben_404(self):
        otro = self.crear_informe('curioso', estado=EstadoTramite.APROBADO_EN_UP, con_cargue=False)
        for usuario in (self.director_ajeno, otro.propuesta.proceso.estudiante_carrera.estudiante.usuario):
            with self.subTest(usuario=usuario.nombre_usuario):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url_descarga).status_code, 404)

    def test_sin_sesion_va_al_login(self):
        self.client.logout()
        respuesta = self.client.get(self.url_descarga)
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('usuarios:login'), respuesta['Location'])

    def test_recibidos_muestra_solo_los_finalizados_de_sus_estudiantes(self):
        pendiente = self.crear_informe('pendiente16', estado=EstadoTramite.APROBADO_EN_UP, con_cargue=False)
        self.client.force_login(pendiente.propuesta.proceso.estudiante_carrera.estudiante.usuario)
        self.subir(pdf('sin_finalizar.pdf'))
        ajeno = self.crear_informe('ajeno16', estado=EstadoTramite.APROBADO_EN_UP, con_cargue=False,
                                   carrera=self.carrera_ajena)
        self.client.force_login(ajeno.propuesta.proceso.estudiante_carrera.estudiante.usuario)
        self.subir(pdf('otra_carrera.pdf'))
        self.finalizar()
        self.client.force_login(self.estudiante)
        self.finalizar()

        self.client.force_login(self.director)
        respuesta = self.client.get(reverse('cargue_up:documentos_extra_recibidos'))
        self.assertContains(respuesta, self.informe.codigo)
        self.assertContains(respuesta, self.url_descarga)
        self.assertNotContains(respuesta, 'sin_finalizar.pdf')
        self.assertNotContains(respuesta, 'otra_carrera.pdf')

    def test_recibidos_vacio(self):
        self.client.force_login(self.director)
        respuesta = self.client.get(reverse('cargue_up:documentos_extra_recibidos'))
        self.assertContains(respuesta, 'Todavía ningún estudiante ha finalizado con documentos extra.')

    def test_recibidos_es_solo_para_directores(self):
        for usuario in (self.estudiante, self.administrador):
            with self.subTest(usuario=usuario.nombre_usuario):
                self.client.force_login(usuario)
                self.assertEqual(
                    self.client.get(reverse('cargue_up:documentos_extra_recibidos')).status_code, 403
                )

    def test_el_aviso_del_dashboard_lleva_a_recibidos(self):
        self.finalizar()
        aviso = Notificacion.objects.get(tipo=servicio.TIPO_NOTIFICACION)
        self.client.force_login(self.director)
        respuesta = self.client.post(reverse('dashboard:abrir_notificacion', args=[aviso.pk]))
        self.assertRedirects(respuesta, reverse('cargue_up:documentos_extra_recibidos'))

    def test_el_dashboard_del_director_enlaza_recibidos(self):
        self.client.force_login(self.director)
        respuesta = self.client.get(reverse('dashboard:director'))
        self.assertContains(respuesta, 'Documentos extra recibidos')
        self.assertContains(respuesta, reverse('cargue_up:documentos_extra_recibidos'))


class ParametrizacionTests(BaseDocumentosExtraTests):
    """El ADMO define el tamaño máximo en Parametrización › Documentos y formatos."""

    def guardar_limites(self, **extra):
        datos = {'max_mb_docx': '10', 'max_mb_csv': '2', 'maximo_filas_csv': '100'}
        datos.update(extra)
        self.client.force_login(self.administrador)
        return self.client.post(reverse('parametrizacion:documentos'), datos)

    def test_el_admo_cambia_el_tamano_maximo(self):
        respuesta = self.guardar_limites(max_mb_documentos_extra='3')
        self.assertRedirects(respuesta, reverse('parametrizacion:documentos'))
        self.assertEqual(servicio.max_mb(), 3)
        self.assertContains(self.client.get(reverse('parametrizacion:documentos')), 'documentos extra (.pdf)')

    def test_si_el_campo_no_llega_se_conserva_el_valor(self):
        self.guardar_limites(max_mb_documentos_extra='3')
        respuesta = self.guardar_limites()
        self.assertRedirects(respuesta, reverse('parametrizacion:documentos'))
        self.assertEqual(servicio.max_mb(), 3)

    def test_valores_fuera_de_rango_no_se_guardan(self):
        for valor in ('0', '51', 'texto'):
            with self.subTest(valor=valor):
                self.assertEqual(self.guardar_limites(max_mb_documentos_extra=valor).status_code, 200)
        self.assertEqual(servicio.max_mb(), 10)
