"""SISTRA-10 · Roles (registro de estudiantes): vistas.

Solo el responsable de este requisito edita este archivo.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.personas.forms.registro_estudiantes import (
    COLUMNAS_DEL_CSV,
    OMITIDO,
    ROL_ESTUDIANTE,
    CargueCsvForm,
    FilaInvalida,
    RegistroEstudianteForm,
    conexion_del_lote,
    maximo_de_filas_csv,
    reabrir_conexion,
    maximo_mb_csv,
    reenviar_credenciales,
    registrar_estudiante,
    sin_tildes,
)
from apps.personas.models import DirectorCarrera, EstadoInscripcion
from apps.usuarios.permisos import requiere_permiso

PLANTILLA = 'personas/registro_estudiantes/registrar.html'

Usuario = get_user_model()


def _carrera_del_director(usuario):
    """La carrera que dirige, o `None`.

    La carrera no se le pregunta al Director: se saca de su asignación vigente,
    y así la regla RN-10-04 («el Director solo ve y registra estudiantes de su
    carrera») no depende de lo que venga en el formulario o en el archivo.
    """
    asignacion = (
        DirectorCarrera.objects.filter(director__usuario=usuario, activo=True)
        .select_related('carrera')
        .order_by('-fecha_inicio', '-id_director_carrera')
        .first()
    )
    return asignacion.carrera if asignacion else None


def _con_credenciales_pendientes(carrera):
    """Los estudiantes de `carrera` que siguen con contraseña temporal.

    Lo usan **las dos** cosas que tienen que coincidir: la lista que se muestra
    y la guarda de la vista que reenvía. Si se escribieran por separado, un día
    la pantalla ofrecería un botón que la vista rechaza, o peor, al revés.

    Las tres condiciones son la regla RN-10-04 puesta en consulta:
    - `rol__nombre=ROL_ESTUDIANTE`: cambiar de rol **no borra** la fila
      `estudiante` ni sus inscripciones, así que un ex-estudiante promovido a
      ADMO seguiría pareciendo «de la carrera». Sin esto, el Director podría
      restablecerle la contraseña a un Administrador.
    - `estado=ACTIVO`: un retirado o un egresado ya no es estudiante vigente,
      igual que no lo es para `_inscribir_estudiante_existente`.
    - la carrera sale de la asignación del Director, nunca de la petición.
    """
    return (
        Usuario.objects.filter(
            requiere_cambio_contrasena=True,
            rol__nombre=ROL_ESTUDIANTE,
            estudiante__inscripciones__carrera=carrera,
            estudiante__inscripciones__estado=EstadoInscripcion.ACTIVO,
        )
        .select_related('rol')
        .distinct()
    )


def _verificar_carrera_de_la_fila(valor, carrera):
    """La columna `carrera` del CSV tiene que ser la del Director (RN-10-04).

    Si viene vacía se asume la suya. Si trae otra, la fila es un error con su
    motivo y no una omisión silenciosa: registrar a alguien en una carrera que
    no es la propia sería saltarse la regla.
    """
    valor = (valor or '').strip()
    if not valor:
        return
    esperados = {sin_tildes(carrera.nombre).strip().lower()}
    if carrera.codigo:
        esperados.add(carrera.codigo.strip().lower())
    if sin_tildes(valor).lower() not in esperados:
        raise FilaInvalida(
            f'La carrera «{valor}» no es la que diriges ({carrera.nombre}).'
        )


def _pantalla(request, carrera, formulario=None, cargue=None, resumen=None):
    return render(
        request,
        PLANTILLA,
        {
            'carrera': carrera,
            'formulario': formulario or RegistroEstudianteForm(),
            'cargue': cargue or CargueCsvForm(),
            'resumen': resumen,
            'columnas': COLUMNAS_DEL_CSV,
            'maximo_filas': maximo_de_filas_csv(),
            'maximo_mb': maximo_mb_csv(),
            # El resumen del cargue solo vive en la respuesta de su POST, así
            # que sin esta lista el Director podría reenviar una vez y perder a
            # los demás. Y es la única vía para el registro uno a uno, que es
            # donde nació el MSG-10-08.
            'pendientes': (
                []
                if carrera is None
                else list(_con_credenciales_pendientes(carrera).order_by('nombre'))
            ),
        },
    )


@requiere_permiso('estudiante.registrar')
def registrar(request):
    """Pantalla del Director: «Uno a uno» y «Archivo CSV».

    El POST de esta vista es el registro uno a uno; el del archivo lo atiende
    `cargar_csv`, que exige su propio permiso.
    """
    carrera = _carrera_del_director(request.user)
    if carrera is None:
        return _pantalla(request, None)

    formulario = RegistroEstudianteForm(request.POST or None)
    if request.method == 'POST' and formulario.is_valid():
        datos = formulario.cleaned_data
        try:
            resultado, usuario, enviado = registrar_estudiante(
                carrera=carrera,
                nombre=datos['nombre'],
                cedula=datos['cedula'],
                correo=datos['correo'],
                autor=request.user,
            )
        except FilaInvalida as error:
            formulario.add_error(None, str(error))
        else:
            if resultado == OMITIDO:
                messages.info(
                    request,
                    f'{usuario.nombre} ya estaba registrado en {carrera.nombre}: '
                    f'no se volvió a cargar.',
                )
            elif enviado is False:
                # MSG-10-08 del BRD. La contraseña temporal solo existe en ese
                # correo, así que callarse el fallo dejaría la cuenta creada e
                # inservible y al Director creyendo que todo salió bien.
                messages.warning(
                    request,
                    f'{datos["nombre"]} quedó registrado en {carrera.nombre}, '
                    f'pero no se pudo enviar el correo con las credenciales a '
                    f'{datos["correo"]}. Hay que reenviarlo.',
                )
            else:
                messages.success(
                    request,
                    f'{datos["nombre"]} quedó registrado en {carrera.nombre}. '
                    f'Ingresará con {datos["correo"]} y una contraseña temporal '
                    f'que le llega a ese correo.',
                )
            return redirect('personas:estudiantes')

    return _pantalla(request, carrera, formulario=formulario)


@requiere_permiso('estudiante.registrar')
@require_POST
def reenviar_credenciales_estudiante(request, id_usuario):
    """Le reenvía las credenciales a un estudiante **de la carrera que dirige**.

    La guarda de carrera no es un extra: sin ella, un Director podría mandar a
    esta ruta el id de un ADMO o de otro Director y restablecerle la contraseña.
    El permiso solo dice que puede registrar estudiantes, no a quién puede
    tocarle la cuenta. Es la misma regla RN-10-04 que aplica el resto de la
    pantalla, y por eso la carrera sale de su asignación y no de la petición.

    La consulta es la misma que arma la lista (`_con_credenciales_pendientes`),
    así que la pantalla y la guarda no pueden decir cosas distintas. Esconder el
    botón en la plantilla no es una regla.
    """
    carrera = _carrera_del_director(request.user)
    if carrera is None:
        return _pantalla(request, None)

    usuario = get_object_or_404(
        _con_credenciales_pendientes(carrera), pk=id_usuario
    )
    # `reenviar_credenciales` audita por dentro, como `registrar_estudiante`.
    if reenviar_credenciales(usuario, autor=request.user):
        messages.success(
            request,
            f'A {usuario.nombre} le acaba de llegar una contraseña temporal '
            f'nueva a {usuario.correo_institucional}.',
        )
    else:
        messages.warning(
            request,
            f'No se pudo enviar el correo a {usuario.correo_institucional}. La '
            f'contraseña temporal se cambió, así que hay que volver a '
            f'intentarlo.',
        )
    return redirect('personas:estudiantes')


@requiere_permiso(('estudiante.registrar', 'estudiante.cargar_csv'))
@require_POST
def cargar_csv(request):
    """Cargue masivo: se procesa fila por fila, no se rechaza el archivo entero.

    Las filas válidas se registran y las inválidas se listan con su motivo
    (flujo alternativo FA-02 del BRD). Solo se rechaza el archivo completo
    cuando no se puede leer, le faltan columnas o pasa del máximo que configuró
    el ADMO en SISTRA-11.
    """
    carrera = _carrera_del_director(request.user)
    if carrera is None:
        return _pantalla(request, None)

    cargue = CargueCsvForm(request.POST, request.FILES)
    if not cargue.is_valid():
        return _pantalla(request, carrera, cargue=cargue)

    try:
        filas = cargue.filas()
    except ValidationError as error:
        # Solo cuando el archivo entero no sirve: no se puede leer, le faltan
        # columnas o pasa del máximo de SISTRA-11.
        cargue.add_error('archivo', error.messages)
        return _pantalla(request, carrera, cargue=cargue)

    registrados, omitidos, sin_correo, errores = 0, 0, 0, []
    # A quiénes no les salió el correo. El número solo no alcanza: sin saber
    # quiénes son, el «hay que reenviárselo» del MSG-10-08 no se puede cumplir.
    sin_correo_detalle = []
    # Una sola conexión de correo para todo el lote: con una por fila, un CSV
    # de 100 estudiantes puede pasarse del tiempo máximo del servidor web y
    # cortarse a la mitad.
    with conexion_del_lote() as conexion:
        for fila in filas:
            try:
                _verificar_carrera_de_la_fila(fila['carrera'], carrera)
                resultado, usuario, enviado = registrar_estudiante(
                    carrera=carrera,
                    nombre=fila['nombre'],
                    cedula=fila['cedula'],
                    correo=fila['correo'],
                    autor=request.user,
                    conexion=conexion,
                )
            except FilaInvalida as error:
                errores.append(
                    {'fila': fila['linea'], 'datos': fila, 'motivo': str(error)}
                )
            else:
                if resultado == OMITIDO:
                    omitidos += 1
                else:
                    registrados += 1
                    if enviado is False:
                        sin_correo += 1
                        sin_correo_detalle.append(
                            {
                                'pk': usuario.pk,
                                'nombre': usuario.nombre,
                                'correo': usuario.correo_institucional,
                            }
                        )
                        reabrir_conexion(conexion)

    resumen = {
        'registrados': registrados,
        'omitidos': omitidos,
        'sin_correo': sin_correo,
        'sin_correo_detalle': sin_correo_detalle,
        'errores': errores,
        'total': len(filas),
    }
    messages.info(
        request,
        f'Se registraron {registrados} estudiantes. {omitidos} ya estaban '
        f'registrados y se omitieron. {len(errores)} filas con error.',
    )
    if sin_correo:
        # MSG-10-08: sin el correo, esas cuentas quedan creadas pero nadie
        # recibió la contraseña temporal.
        messages.warning(
            request,
            f'A {sin_correo} de los registrados no se les pudo enviar el correo '
            f'con las credenciales. Hay que reenviárselo.',
        )
    return _pantalla(request, carrera, resumen=resumen)
