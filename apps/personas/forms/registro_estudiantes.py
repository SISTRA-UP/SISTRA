"""SISTRA-10 · Roles (registro de estudiantes): formularios.

Solo el responsable de este requisito edita este archivo.

Aquí vive también `registrar_estudiante()`, que es la lógica que comparten las
dos formas de registrar —uno a uno y por CSV— para que las dos se comporten
igual. No está en un módulo de servicios aparte porque la lista de archivos de
este requisito (README §3) no contempla uno, y partirla en dos sitios haría que
el CSV y el formulario se fueran separando con el tiempo.
"""

import csv
import io
import re
import unicodedata

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.parametrizacion.models import Parametro
from apps.personas.models import EstadoInscripcion, Estudiante, EstudianteCarrera
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.seguimiento.models import Auditoria
from apps.usuarios.models import Estado, Rol

Usuario = get_user_model()

ROL_ESTUDIANTE = 'Estudiante'

# Qué pasó con cada estudiante. El resumen del BRD (MSG-10-07) cuenta
# CREADO + INSCRITO como «registrados», OMITIDO como «ya estaban registrados».
CREADO = 'creado'
INSCRITO = 'inscrito'
OMITIDO = 'omitido'

COLUMNAS_DEL_CSV = ('nombre', 'cedula', 'correo', 'carrera')

# `str.isdigit()` no sirve para validar una cédula: acepta superíndices (`1²3`)
# y dígitos árabe-índicos (`١٢٣`), que quedarían guardados en la columna y nunca
# volverían a coincidir con la cédula real. La cédula es la clave de identidad
# de todo el contrato, así que se exige dígitos ASCII y nada más.
CEDULA = re.compile(r'[0-9]{1,15}\Z')
SOLO_DIGITOS = re.compile(r'[0-9]+\Z')

# Límite técnico propio, mientras SISTRA-11 no defina uno: el BRD acota el
# cargue por **filas** (NUM-FILAS-CSV), no por tamaño, y sin un tope el archivo
# se lee entero en memoria antes de poder contar sus filas. 5 MB son del orden
# de 60.000 filas de este formato, muy por encima de cualquier cohorte real.
TAMANO_MAXIMO_DEL_ARCHIVO = 5 * 1024 * 1024

# Clave del parámetro con el máximo de filas por cargue (BRD §5.12,
# NUM-FILAS-CSV). La configura el ADMO en SISTRA-11; **el nombre exacto está por
# confirmar con Ivan Ospino**. Si no está configurada, no se limita.
CLAVE_MAXIMO_FILAS_CSV = 'registro_estudiantes.maximo_filas_csv'


class FilaInvalida(Exception):
    """Un registro que no se puede hacer, con el motivo para mostrárselo.

    Lo usan las dos pantallas: en el cargue CSV se convierte en una fila del log
    de errores, y en el registro uno a uno en el mensaje del formulario.
    """


def sin_tildes(texto):
    return (
        unicodedata.normalize('NFKD', texto or '')
        .encode('ascii', 'ignore')
        .decode('ascii')
    )


def nombre_usuario_libre(correo, excluir=None):
    """La parte del correo anterior a la `@`, con número si ya está tomada.

    Es la invariante que publica `CONTRATO_MODULO.md` y la nota técnica del BRD
    §5.11. La misma regla la aplica el formulario de usuarios de SISTRA-10; hay
    que unificarlas cuando se pueda tocar los dos archivos en un mismo issue.
    """
    base = (correo.split('@')[0] or 'usuario').strip().lower()[:80]
    tomados = Usuario.objects.all()
    if excluir is not None:
        tomados = tomados.exclude(pk=excluir)
    candidato, siguiente = base, 2
    while tomados.filter(nombre_usuario=candidato).exists():
        sufijo = f'-{siguiente}'
        candidato = f'{base[: 80 - len(sufijo)]}{sufijo}'
        siguiente += 1
    return candidato


def maximo_de_filas_csv():
    """El máximo de filas por cargue, o `None` si SISTRA-11 no lo configuró."""
    parametro = Parametro.objects.filter(clave=CLAVE_MAXIMO_FILAS_CSV).first()
    if parametro is None:
        return None
    valor = str(parametro.valor or '').strip()
    # No se usa `int()` a secas porque acepta guiones bajos (`int('1_0') == 10`)
    # y signos; un parámetro mal escrito tiene que caer en "sin límite", no en
    # un límite distinto del que el ADMO creyó configurar.
    if not SOLO_DIGITOS.match(valor):
        return None
    maximo = int(valor)
    return maximo if maximo > 0 else None


def _auditar(autor, accion, tabla, id_registro=None, detalle='', resultado='Éxito'):
    Auditoria.objects.create(
        usuario=autor if getattr(autor, 'is_authenticated', False) else None,
        accion=accion[:100],
        tabla_afectada=tabla[:80],
        id_registro_afectado=id_registro,
        detalle=detalle,
        resultado=resultado[:30],
    )


def enviar_credenciales(usuario, contrasena):
    """Manda el correo con el usuario y la contraseña temporal (RG-09).

    Devuelve `True` o `False`: si falla, **la cuenta queda creada igual** y el
    fallo se registra, que es lo que manda el BRD en su excepción EX-03. El
    texto es mínimo a propósito: la plantilla del correo es SIS-37
    (daniel.luna21) y el servicio de envío SIS-38 (Fabiano Del Villar). Cuando
    exista el servicio, los correos empiezan a salir sin tocar esta función.
    """
    try:
        send_mail(
            subject='SISTRA · Tus datos de acceso',
            message=(
                f'Hola {usuario.nombre}.\n\n'
                f'Ya tienes cuenta en SISTRA para tu Trabajo Social.\n\n'
                f'Ingresa con tu correo institucional: {usuario.correo_institucional}\n'
                f'Contraseña temporal: {contrasena}\n\n'
                f'Por seguridad, el sistema te pedirá cambiarla la primera vez '
                f'que ingreses.'
            ),
            from_email=None,
            recipient_list=[usuario.correo_institucional],
            fail_silently=False,
        )
        return True
    except Exception:
        # Cualquier falla del correo (sin servicio configurado, servidor caído,
        # dirección rechazada) no puede tumbar el registro: EX-03 del BRD.
        return False


def _validar(nombre, cedula, correo):
    """Devuelve los tres datos limpios o levanta `FilaInvalida` con el motivo."""
    nombre = (nombre or '').strip()
    cedula = (cedula or '').strip()
    correo = (correo or '').strip().lower()

    if not nombre:
        raise FilaInvalida('Falta el nombre.')
    if len(nombre) > 120:
        raise FilaInvalida('El nombre pasa de 120 caracteres.')
    # Un archivo con basura binaria trae bytes de control, y un NUL en el nombre
    # llega hasta PostgreSQL, que lo rechaza con un error de base de datos y
    # tumbaría el cargue entero en vez de dejar una fila con motivo.
    if any(caracter < ' ' for caracter in nombre):
        raise FilaInvalida('El nombre trae caracteres no imprimibles.')
    if not cedula:
        raise FilaInvalida('Falta la cédula.')
    if not CEDULA.match(cedula):
        raise FilaInvalida('La cédula debe tener solo dígitos (máximo 15).')
    if not correo:
        raise FilaInvalida('Falta el correo institucional.')
    if len(correo) > 254:
        raise FilaInvalida('El correo pasa de 254 caracteres.')
    try:
        validate_email(correo)
    except forms.ValidationError:
        raise FilaInvalida('El correo no tiene un formato válido.')
    return nombre, cedula, correo


def _usuario_existente(cedula, correo):
    """El usuario que ya tiene esa cédula o ese correo.

    Si la cédula y el correo apuntan a **personas distintas**, o si uno coincide
    y el otro no, eso no es «ya estaba registrado»: es un dato mal escrito o dos
    personas confundidas, así que es un error de fila. Omitirlo en silencio
    dejaría al estudiante sin cuenta sin que nadie se entere.
    """
    por_cedula = Usuario.objects.filter(cedula=cedula).first()
    por_correo = Usuario.objects.filter(correo_institucional=correo).first()

    if por_cedula and por_correo and por_cedula.pk != por_correo.pk:
        raise FilaInvalida(
            'La cédula y el correo están registrados en dos cuentas distintas.'
        )
    if por_cedula and not por_correo:
        raise FilaInvalida(
            f'La cédula ya está registrada con otro correo '
            f'({por_cedula.correo_institucional}).'
        )
    if por_correo and not por_cedula:
        raise FilaInvalida(
            f'El correo ya está registrado con otra cédula ({por_correo.cedula}).'
        )
    return por_cedula or por_correo


def registrar_estudiante(*, carrera, nombre, cedula, correo, autor):
    """Registra a un estudiante en `carrera`.

    Devuelve `(resultado, usuario, enviado)`, donde `enviado` dice si el correo
    con las credenciales salió: `True`, `False`, o `None` cuando no había que
    mandar ninguno (el estudiante ya tenía cuenta). **Quien llame tiene que
    mirar ese valor**: si es `False`, la cuenta quedó creada pero nadie recibió
    la contraseña, y hay que decírselo al Director (MSG-10-08 del BRD).

    El correo se manda **después** de confirmar la transacción, a propósito: si
    se mandara dentro y algo fallara después, el estudiante recibiría las
    credenciales de una cuenta que se revirtió. Y con un servidor SMTP lento,
    cada fila mantendría abierta una transacción durante todo el ida y vuelta.
    """
    resultado, usuario, contrasena = _registrar_en_la_base(
        carrera=carrera, nombre=nombre, cedula=cedula, correo=correo, autor=autor
    )
    if contrasena is None:
        return resultado, usuario, None

    enviado = enviar_credenciales(usuario, contrasena)
    _auditar(
        autor,
        'Enviar credenciales',
        'usuario',
        usuario.pk,
        f'correo: {usuario.correo_institucional}',
        'Éxito' if enviado else 'Fallo',
    )
    return resultado, usuario, enviado


@transaction.atomic
def _registrar_en_la_base(*, carrera, nombre, cedula, correo, autor):
    """Todo lo que toca la base, en una sola transacción.

    Los tres caminos salen del BRD §5.11 y de la respuesta del PO del
    2026-11-07, que aceptó que el ADMO cree un Estudiante sin carrera:

    - **CREADO:** no existía. Se le crea la cuenta con rol Estudiante, su
      perfil, la inscripción, el proceso de Trabajo Social, y se le manda la
      contraseña temporal.
    - **INSCRITO:** ya existía (en otra carrera, o sin ninguna). **No se le
      crea otra cuenta ni se le manda contraseña nueva**: solo se le agrega la
      inscripción y su proceso. Aquí entra el usuario que crea el ADMO, que de
      otro modo se quedaría para siempre sin poder empezar su Trabajo Social.
    - **OMITIDO:** ya estaba inscrito en esta misma carrera.

    Levanta `FilaInvalida` con el motivo cuando los datos no sirven. Devuelve
    `(resultado, usuario, contrasena)`; la contraseña en claro solo viene cuando
    se creó una cuenta nueva, y es lo único que sale de aquí sin cifrar: se usa
    para el correo y no se guarda ni se audita en ninguna parte.
    """
    nombre, cedula, correo = _validar(nombre, cedula, correo)
    usuario = _usuario_existente(cedula, correo)

    if usuario is None:
        return _crear_estudiante_nuevo(carrera, nombre, cedula, correo, autor)

    resultado, usuario = _inscribir_estudiante_existente(carrera, usuario, autor)
    return resultado, usuario, None


def _crear_estudiante_nuevo(carrera, nombre, cedula, correo, autor):
    rol = Rol.objects.filter(nombre=ROL_ESTUDIANTE).first()
    if rol is None:
        raise FilaInvalida(
            'No existe el rol Estudiante: falta correr las migraciones.'
        )
    if rol.estado != Estado.ACTIVO:
        raise FilaInvalida('El rol Estudiante está inactivo.')

    contrasena = get_random_string(16)
    try:
        usuario = Usuario.objects.create_user(
            correo_institucional=correo,
            password=contrasena,
            nombre=nombre,
            cedula=cedula,
            nombre_usuario=nombre_usuario_libre(correo),
            rol=rol,
            requiere_cambio_contrasena=True,
        )
    except ValidationError as error:
        # `create_user` corre `full_clean()`: si dos cargues simultáneos traen
        # al mismo estudiante, el segundo choca con la restricción única. Eso es
        # una fila con motivo, no un error 500.
        raise FilaInvalida('; '.join(error.messages))

    _inscribir(carrera, usuario)
    _auditar(
        autor,
        'Registrar estudiante',
        'usuario',
        usuario.pk,
        f'nombre: {nombre} · cedula: {cedula} · correo: {correo} · '
        f'carrera: {carrera.nombre}',
    )
    return CREADO, usuario, contrasena


def _inscribir_estudiante_existente(carrera, usuario, autor):
    if usuario.rol.nombre != ROL_ESTUDIANTE:
        raise FilaInvalida(
            f'Esa cédula ya tiene cuenta con rol {usuario.rol.nombre}.'
        )
    if usuario.estado != Estado.ACTIVO:
        # Inscribirlo igual lo dejaría «registrado» para el Director y sin poder
        # entrar nunca: `is_active` sería False y `has_perm` devolvería False.
        raise FilaInvalida(
            'Esa cuenta está inactiva: pídele al administrador que la reactive '
            'antes de inscribirlo.'
        )

    inscripcion = (
        EstudianteCarrera.objects.filter(estudiante__usuario=usuario, carrera=carrera)
        .select_related('estudiante')
        .first()
    )
    if inscripcion is not None:
        if inscripcion.estado != EstadoInscripcion.ACTIVO:
            # La restricción única (estudiante, carrera) impide abrirle otra, y
            # reactivar una inscripción es una decisión de negocio que nadie ha
            # tomado todavía. Se dice, en vez de omitirlo en silencio y dejarlo
            # sin salida por ninguna pantalla.
            raise FilaInvalida(
                f'Ya tuvo una inscripción en {carrera.nombre} y quedó en estado '
                f'«{inscripcion.estado}»: reactivarla no se puede desde aquí.'
            )
        # Una inscripción sin proceso no es alcanzable hoy —solo este módulo las
        # crea, y siempre con su proceso—, pero falta acordar quién más escribe
        # en `estudiante_carrera`. Si llega a pasar, el estudiante se quedaría
        # omitido para siempre y sin con qué empezar su Trabajo Social.
        ProcesoTrabajoSocial.objects.get_or_create(
            estudiante_carrera=inscripcion,
            defaults={
                'fecha_inicio': timezone.now(),
                'estado': EstadoAvance.PENDIENTE,
            },
        )
        return OMITIDO, usuario

    inscripcion = _inscribir(carrera, usuario)
    _auditar(
        autor,
        'Inscribir estudiante en carrera',
        'estudiante_carrera',
        inscripcion.pk,
        f'correo: {usuario.correo_institucional} · carrera: {carrera.nombre}',
    )
    return INSCRITO, usuario


def _inscribir(carrera, usuario):
    """Perfil, inscripción y proceso de Trabajo Social de esa carrera.

    El proceso se crea aquí porque el BRD §5.11, flujo C paso 5, dice que al
    registrar al estudiante en una carrera «se crea su proceso de Trabajo
    Social», y la RG-01 que hay **un proceso por carrera**: en el modelo eso es
    un `OneToOneField` contra la inscripción.
    """
    estudiante, _ = Estudiante.objects.get_or_create(usuario=usuario)
    inscripcion = EstudianteCarrera.objects.create(
        estudiante=estudiante,
        carrera=carrera,
        estado=EstadoInscripcion.ACTIVO,
    )
    ProcesoTrabajoSocial.objects.create(
        estudiante_carrera=inscripcion,
        fecha_inicio=timezone.now(),
        estado=EstadoAvance.PENDIENTE,
    )
    return inscripcion


class RegistroEstudianteForm(forms.Form):
    """Registro uno a uno. La carrera no se pide: es la del Director (RN-10-04)."""

    nombre = forms.CharField(
        max_length=120,
        label='Nombre completo',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
    )
    cedula = forms.CharField(
        max_length=15,
        label='Cédula',
        widget=forms.TextInput(attrs={'class': 'form-control', 'inputmode': 'numeric'}),
    )
    correo = forms.EmailField(
        max_length=254,
        label='Correo institucional',
        help_text='Ahí le llegará su contraseña temporal, y con ese correo ingresa.',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )


class CargueCsvForm(forms.Form):
    """Cargue masivo. La plantilla del archivo la provee SISTRA-11."""

    archivo = forms.FileField(
        label='Archivo CSV',
        help_text=f'Columnas: {", ".join(COLUMNAS_DEL_CSV)}.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.csv'}),
    )

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if not archivo.name.lower().endswith('.csv'):
            raise forms.ValidationError(
                'El archivo no es un CSV con la plantilla de SISTRA.'
            )
        # Se mira el tamaño antes de leerlo: si no, un archivo enorme se carga
        # entero en memoria y se parsea solo para rechazarlo después.
        if archivo.size > TAMANO_MAXIMO_DEL_ARCHIVO:
            megas = TAMANO_MAXIMO_DEL_ARCHIVO // (1024 * 1024)
            raise forms.ValidationError(
                f'El archivo pesa más de {megas} MB: divídelo en varios cargues.'
            )
        return archivo

    def filas(self):
        """Las filas del archivo, ya con sus columnas reconocidas.

        Levanta `forms.ValidationError` si el archivo entero no sirve: no se
        puede leer, le faltan columnas o pasa del máximo que configuró el ADMO.
        """
        return leer_filas_csv(self.cleaned_data['archivo'])


def leer_filas_csv(archivo):
    crudo = archivo.read()
    if isinstance(crudo, str):
        crudo = crudo.encode('utf-8')

    texto = None
    for codificacion in ('utf-8-sig', 'cp1252'):
        try:
            texto = crudo.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise forms.ValidationError(
            'No se pudo leer el archivo: guárdalo como CSV en UTF-8.'
        )

    texto = texto.strip()
    if not texto:
        raise forms.ValidationError('El archivo está vacío.')

    # Excel en Windows exporta con punto y coma; si no se detecta, el Director
    # sube su archivo y le sale «formato inválido» sin entender por qué.
    try:
        delimitador = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=',;\t').delimiter
    except csv.Error:
        delimitador = ','

    lector = csv.DictReader(io.StringIO(texto), delimiter=delimitador)
    try:
        encabezados = {
            sin_tildes(c).strip().lower(): c for c in (lector.fieldnames or [])
        }
    except csv.Error:
        raise forms.ValidationError(
            'El archivo está mal formado y no se pudo leer su primera línea.'
        )

    faltan = [c for c in COLUMNAS_DEL_CSV if c not in encabezados]
    if faltan:
        raise forms.ValidationError(
            f'El archivo no es un CSV con la plantilla de SISTRA: '
            f'le faltan las columnas {", ".join(faltan)}.'
        )

    maximo = maximo_de_filas_csv()
    filas = []
    try:
        for cruda in lector:
            # `line_num` es la línea **del archivo**, que es la que el Director
            # ve en Excel. Contar las filas devueltas se desalinearía, porque el
            # lector descarta las líneas en blanco.
            fila = {'linea': lector.line_num}
            for columna in COLUMNAS_DEL_CSV:
                fila[columna] = (cruda.get(encabezados[columna]) or '').strip()
            filas.append(fila)
            if maximo is not None and len(filas) > maximo:
                raise forms.ValidationError(
                    f'El archivo trae más filas de las permitidas: '
                    f'el máximo por cargue es {maximo}.'
                )
    except csv.Error:
        # Una comilla sin cerrar hace que el lector trague el resto del archivo
        # como un solo campo y reviente al pasar el límite de tamaño de campo.
        # Sin esta guarda, el Director recibe un 500 en vez del log de errores.
        raise forms.ValidationError(
            f'El archivo está mal formado desde la línea {lector.line_num}: '
            f'revisa que no haya comillas sin cerrar.'
        )

    if not filas:
        raise forms.ValidationError('El archivo no tiene ninguna fila de datos.')
    return filas
