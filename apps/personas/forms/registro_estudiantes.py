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
from contextlib import contextmanager, suppress

from django import forms
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string

from apps.parametrizacion.servicios import obtener_entero
from apps.personas.models import EstadoInscripcion, Estudiante, EstudianteCarrera
from apps.procesos.models import EstadoAvance, ProcesoTrabajoSocial
from apps.seguimiento.models import Auditoria
# Un solo lugar para el dominio: lo define el login (SISTRA-13), que es quien lo exige.
from apps.usuarios.forms.logueo import DOMINIO_INSTITUCIONAL
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

# Los dos límites del cargue los configura el ADMO en SISTRA-11 y aquí solo se
# leen: el tamaño en MB y el máximo de filas (BRD §5.12, NUM-FILAS-CSV). Los
# valores de respaldo son los mismos que declara `parametrizacion/servicios.py`,
# porque la tabla `parametro` está vacía mientras el ADMO no guarde nada.
CLAVE_MAX_MB_CSV = 'registro_estudiantes.max_mb_csv'
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


def _limite(clave, por_defecto):
    """Un límite de SISTRA-11, o su valor de respaldo si el guardado no sirve.

    La pantalla que los guarda exige un entero >= 1, así que el respaldo solo
    cubre una fila editada a mano en la base: un límite de 0 o negativo
    rechazaría todos los archivos y dejaría el cargue inservible.
    """
    valor = obtener_entero(clave, por_defecto)
    return valor if valor > 0 else por_defecto


def maximo_mb_csv():
    """El tamaño máximo del archivo, en MB."""
    return _limite(CLAVE_MAX_MB_CSV, 2)


def maximo_de_filas_csv():
    """El máximo de filas por cargue."""
    return _limite(CLAVE_MAXIMO_FILAS_CSV, 100)


def _auditar(autor, accion, tabla, id_registro=None, detalle='', resultado='Éxito'):
    Auditoria.objects.create(
        usuario=autor if getattr(autor, 'is_authenticated', False) else None,
        accion=accion[:100],
        tabla_afectada=tabla[:80],
        id_registro_afectado=id_registro,
        detalle=detalle,
        resultado=resultado[:30],
    )


@contextmanager
def conexion_del_lote():
    """Una sola conexión de correo para todo un cargue masivo.

    Hay que **abrirla aquí**: el backend SMTP solo cierra la conexión que abrió
    él (`if new_conn_created: self.close()`), así que si se pasa sin abrir, el
    primer `send_mail` la abre y la cierra, y se vuelve a una conexión por fila.

    Crearla y abrirla van las dos dentro de la guarda, y lo que se entrega puede
    ser `None`: con `MAILERS`, **construir** la conexión ya puede fallar (un
    `.env` con `use_ssl` y `use_tls` a la vez levanta `InvalidMailer` en el
    constructor del backend). Nada de eso puede tumbar el cargue: con `None`
    cada fila abre la suya, y si la que falla es la apertura, cada envío falla y
    se audita. El correo no condiciona el registro (EX-03 del BRD).

    No se le pasa `fail_silently`: `get_connection` solo lo reenvía cuando es
    verdadero, y el valor por defecto del backend ya es `False`, que es el que
    hace falta. Una conexión silenciosa sería lo peligroso: un servidor caído no
    lanzaría nada y el envío se auditaría como «Éxito» sin haber salido.
    """
    conexion = None
    try:
        with suppress(Exception):
            conexion = mail.get_connection()
            conexion.open()
        yield conexion
    finally:
        if conexion is not None:
            with suppress(Exception):
                conexion.close()


def reabrir_conexion(conexion):
    """Renueva la conexión del lote después de un envío fallido.

    El fallo pudo ser de la conexión y no del destinatario (el servidor corta,
    el protocolo se desincroniza). Django **no la cierra**, porque solo cierra
    la que abrió él, y `open()` devuelve `False` mientras el atributo siga
    puesto: una conexión muerta haría fallar también a **todas** las filas
    siguientes, y una fila mala arrastraría al resto. Renovarla cuesta una
    reconexión y mantiene lo que pide la tarjeta: si uno falla, los demás salen.
    """
    if conexion is None:
        return
    with suppress(Exception):
        conexion.close()
    with suppress(Exception):
        conexion.open()


def enviar_credenciales(usuario, contrasena, conexion=None):
    """Manda el correo con el usuario y la contraseña temporal (RG-09).

    Devuelve `True` o `False`: si falla, **la cuenta queda creada igual** y el
    fallo se registra, que es lo que manda el BRD en su excepción EX-03. El
    texto es mínimo a propósito: la plantilla del correo es SIS-37
    (daniel.luna21) y el servicio de envío SIS-38 (Fabiano Del Villar). Cuando
    exista el servicio, los correos empiezan a salir sin tocar esta función.

    `conexion` es opcional y **la firma de dos argumentos sigue siendo válida**:
    sin ella se abre una por envío, como siempre. El cargue masivo pasa una sola
    para todo el lote (E12).
    """
    try:
        return send_mail(
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
            connection=conexion,
        ) == 1
    except Exception:
        # Cualquier falla del correo (sin servicio configurado, servidor caído,
        # dirección rechazada) no puede tumbar el registro: EX-03 del BRD.
        return False


def reenviar_credenciales(usuario, *, autor):
    """Le pone una contraseña temporal nueva y se la manda (R5 · MSG-10-08).

    Reenviar no es volver a mandar lo mismo: la contraseña anterior **solo
    existía en el correo que no salió** —en la base está su hash—, así que no
    hay nada que reenviar. Se genera otra.

    Se guarda **antes** de mandar el correo, a propósito: si el envío falla, la
    cuenta queda con una contraseña temporal consistente y el botón se puede
    volver a pulsar. Al revés se habría mandado una contraseña distinta de la
    que quedó guardada.

    **Desbloquea la cuenta**, y no es un extra: el login rechaza la sesión
    aunque la contraseña sea correcta mientras `bloqueado_hasta` siga en el
    futuro. Y el caso típico de R5 es justo ese — a alguien no le llegó el
    correo, intentó entrar a ciegas hasta bloquearse y pidió ayuda —, así que
    sin esto el botón mandaría una contraseña que no sirve y el mensaje diría
    que sí. Es lo mismo que hacen los otros dos sitios que ponen una contraseña
    temporal (`logueo.py`, recuperación y cambio de contraseña).

    El cambio y su auditoría van en una transacción, como el alta de usuario de
    SIS-69: si la auditoría falla, una contraseña cambiada sin rastro sería peor
    que no haberla cambiado.

    Audita aquí mismo, como `registrar_estudiante`, para que ninguna de las dos
    pantallas que la usan pueda olvidarlo. El **envío** no lanza nunca (lo
    garantiza `enviar_credenciales`); un fallo de base de datos sí sale, y debe
    salir. `autor` va solo por nombre para que no se pueda confundir con el
    segundo parámetro de `enviar_credenciales`, que es la contraseña.
    """
    contrasena = get_random_string(16)
    with transaction.atomic():
        usuario.set_password(contrasena)
        # Sigue siendo temporal: hay que cambiarla en el primer ingreso.
        usuario.requiere_cambio_contrasena = True
        usuario.intentos_fallidos = 0
        usuario.bloqueado_hasta = None
        usuario.save(
            update_fields=[
                'password',
                'requiere_cambio_contrasena',
                'intentos_fallidos',
                'bloqueado_hasta',
            ]
        )
        enviado = enviar_credenciales(usuario, contrasena)
        _auditar(
            autor,
            'Reenviar credenciales',
            'usuario',
            usuario.pk,
            f'correo: {usuario.correo_institucional}',
            'Éxito' if enviado else 'Fallo',
        )
    return enviado


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
    if correo.rsplit('@', 1)[-1] != DOMINIO_INSTITUCIONAL:
        raise FilaInvalida(
            f'El correo tiene que ser institucional, con el dominio '
            f'@{DOMINIO_INSTITUCIONAL}.'
        )
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


def registrar_estudiante(*, carrera, nombre, cedula, correo, autor, conexion=None):
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

    `conexion` es la del lote cuando quien llama es el cargue masivo (E12); sin
    ella se abre una por envío.
    """
    resultado, usuario, contrasena = _registrar_en_la_base(
        carrera=carrera, nombre=nombre, cedula=cedula, correo=correo, autor=autor
    )
    if contrasena is None:
        return resultado, usuario, None

    enviado = enviar_credenciales(usuario, contrasena, conexion)
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
        megas = maximo_mb_csv()
        if archivo.size > megas * 1024 * 1024:
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
            if len(filas) > maximo:
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
