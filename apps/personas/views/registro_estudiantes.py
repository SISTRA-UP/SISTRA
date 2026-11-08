"""SISTRA-10 · Roles (registro de estudiantes): vistas.

Solo el responsable de este requisito edita este archivo.
"""

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.personas.forms.registro_estudiantes import (
    COLUMNAS_DEL_CSV,
    OMITIDO,
    CargueCsvForm,
    FilaInvalida,
    RegistroEstudianteForm,
    maximo_de_filas_csv,
    registrar_estudiante,
    sin_tildes,
)
from apps.personas.models import DirectorCarrera

PLANTILLA = 'personas/registro_estudiantes/registrar.html'


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
        },
    )


@permission_required('estudiante.registrar', raise_exception=True)
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


@permission_required(
    ('estudiante.registrar', 'estudiante.cargar_csv'), raise_exception=True
)
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
    for fila in filas:
        try:
            _verificar_carrera_de_la_fila(fila['carrera'], carrera)
            resultado, _, enviado = registrar_estudiante(
                carrera=carrera,
                nombre=fila['nombre'],
                cedula=fila['cedula'],
                correo=fila['correo'],
                autor=request.user,
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

    resumen = {
        'registrados': registrados,
        'omitidos': omitidos,
        'sin_correo': sin_correo,
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
