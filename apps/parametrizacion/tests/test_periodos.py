from django.test import TestCase
from django.urls import reverse

from apps.parametrizacion.models import EstadoPeriodo, PeriodoAcademico
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Rol, Usuario


class PeriodosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser(
            'admin@unipamplona.edu.co', 'Clave-Segura-123',
            nombre='Admin', cedula='900000001', nombre_usuario='admin',
        )
        rol_dir, _ = Rol.objects.get_or_create(nombre='Director')
        cls.director = Usuario.objects.create_user(
            correo_institucional='diana@unipamplona.edu.co',
            password='Director-Test-1',
            nombre='Diana Rojas',
            cedula='900000002',
            nombre_usuario='diana.rojas',
            rol=rol_dir,
            requiere_cambio_contrasena=False,
        )
        cls.lista = reverse('parametrizacion:periodos')
        cls.nuevo = reverse('parametrizacion:periodo_nuevo')

    def setUp(self):
        self.client.force_login(self.admin)

    def datos(self, **cambios):
        datos = {
            'nombre': '2026-2', 'fecha_inicio': '2026-08-01', 'fecha_fin': '2026-12-15',
            'fecha_cierre_propuesta': '2026-08-31', 'fecha_cierre_informe': '2026-11-30',
            'estado': 'Cerrado',
        }
        datos.update(cambios)
        return datos

    def crear(self, **cambios):
        campos = {
            'nombre': '2026-1', 'fecha_inicio': '2026-02-01', 'fecha_fin': '2026-06-15',
            'fecha_cierre_propuesta': '2026-02-28', 'fecha_cierre_informe': '2026-05-30',
            'estado': EstadoPeriodo.CERRADO,
        }
        campos.update(cambios)
        return PeriodoAcademico.objects.create(**campos)

    def test_el_director_no_entra(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(self.lista).status_code, 403)
        self.assertEqual(self.client.get(self.nuevo).status_code, 403)

    def test_lista_vacia(self):
        self.assertContains(self.client.get(self.lista), 'Todavía no hay periodos')

    def test_lista_muestra_los_periodos(self):
        self.crear()
        respuesta = self.client.get(self.lista)
        self.assertContains(respuesta, '2026-1')
        self.assertContains(respuesta, '01/02/2026')

    def test_crea_periodo_y_audita(self):
        respuesta = self.client.post(self.nuevo, self.datos())
        self.assertRedirects(respuesta, self.lista)
        self.assertTrue(PeriodoAcademico.objects.filter(nombre='2026-2').exists())
        self.assertTrue(Auditoria.objects.filter(
            accion='Crear periodo académico', usuario=self.admin).exists())

    def test_nombre_con_formato_invalido(self):
        respuesta = self.client.post(self.nuevo, self.datos(nombre='2026'))
        self.assertContains(respuesta, 'aaaa-n')
        self.assertFalse(PeriodoAcademico.objects.exists())

    def test_nombre_repetido(self):
        self.crear()
        respuesta = self.client.post(self.nuevo, self.datos(nombre='2026-1'))
        self.assertContains(respuesta, 'Ya existe un periodo con ese nombre.')

    def test_fin_anterior_al_inicio(self):
        respuesta = self.client.post(self.nuevo, self.datos(fecha_fin='2026-07-01'))
        self.assertContains(respuesta, 'El fin del periodo no puede ser anterior al inicio.')

    def test_cierre_de_propuesta_fuera_del_periodo(self):
        respuesta = self.client.post(self.nuevo, self.datos(fecha_cierre_propuesta='2027-01-10'))
        self.assertContains(respuesta, 'El cierre de la propuesta debe estar dentro del periodo.')

    def test_cierre_de_informe_no_posterior(self):
        respuesta = self.client.post(self.nuevo, self.datos(fecha_cierre_informe='2026-08-31'))
        self.assertContains(respuesta, 'El cierre del informe debe ser posterior')

    def test_otro_vigente_pide_confirmacion(self):
        self.crear(estado=EstadoPeriodo.VIGENTE)
        respuesta = self.client.post(self.nuevo, self.datos(estado='Vigente'))
        self.assertContains(respuesta, 'Pasará a Cerrado')
        self.assertFalse(PeriodoAcademico.objects.filter(nombre='2026-2').exists())
        self.assertEqual(PeriodoAcademico.objects.get(nombre='2026-1').estado, 'Vigente')

    def test_confirmando_se_cierra_el_anterior(self):
        self.crear(estado=EstadoPeriodo.VIGENTE)
        respuesta = self.client.post(self.nuevo, self.datos(estado='Vigente', confirmar='1'))
        self.assertRedirects(respuesta, self.lista)
        self.assertEqual(PeriodoAcademico.objects.get(nombre='2026-1').estado, 'Cerrado')
        self.assertEqual(PeriodoAcademico.objects.get(nombre='2026-2').estado, 'Vigente')
        self.assertTrue(Auditoria.objects.filter(accion='Cerrar periodo académico').exists())

    def test_editar_cambia_las_fechas(self):
        periodo = self.crear()
        url = reverse('parametrizacion:periodo_editar', args=[periodo.pk])
        respuesta = self.client.post(url, self.datos(
            nombre='2026-1', fecha_inicio='2026-02-01', fecha_fin='2026-06-30',
            fecha_cierre_propuesta='2026-03-05', fecha_cierre_informe='2026-06-10',
        ))
        self.assertRedirects(respuesta, self.lista)
        periodo.refresh_from_db()
        self.assertEqual(str(periodo.fecha_cierre_informe), '2026-06-10')

    def test_editar_el_vigente_no_pide_confirmacion(self):
        periodo = self.crear(estado=EstadoPeriodo.VIGENTE)
        url = reverse('parametrizacion:periodo_editar', args=[periodo.pk])
        respuesta = self.client.post(url, self.datos(
            nombre='2026-1', estado='Vigente', fecha_inicio='2026-02-01', fecha_fin='2026-06-15',
            fecha_cierre_propuesta='2026-02-28', fecha_cierre_informe='2026-05-30',
        ))
        self.assertRedirects(respuesta, self.lista)

    def test_no_se_pueden_eliminar_periodos(self):
        periodo = self.crear()
        respuesta = self.client.post(f'/parametrizacion/periodos/{periodo.pk}/eliminar/')
        self.assertEqual(respuesta.status_code, 404)
        self.assertTrue(PeriodoAcademico.objects.filter(pk=periodo.pk).exists())